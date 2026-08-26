"""
MODULE 1 - ADO (Action Decomposed Operators)

PURPOSE:
- Select and decompose operators needed to answer the query
- ADO does NOT plan execution order
- ADO does NOT execute code
- ADO does NOT evaluate paths

INPUT:
- Natural language query
- Table metadata (schema, column types, time columns)

OUTPUT:
- A SET of operator nodes (NOT ordered, NOT a tree)
"""

import json
import re
from typing import List, Dict, Any, Optional
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.dtr_structures import Operator, OperatorType, ADOResult


# Fixed Operator Pool
OPERATOR_POOL = [
    Operator(
        name="DETECT_SCHEMA",
        category=OperatorType.DATA_UNDERSTANDING,
        description="Detect table structure: column names, types, null counts",
        estimated_cost=0.5,
        semantic_description="Identifies the schema of the input table"
    ),
    Operator(
        name="INSPECT_COLUMN",
        category=OperatorType.DATA_UNDERSTANDING,
        description="Inspect specific column: statistics, unique values, data distribution",
        estimated_cost=0.8,
        semantic_description="Analyzes a specific column for understanding its properties"
    ),
    Operator(
        name="FILTER_ROWS",
        category=OperatorType.FILTERING_EXTRACTION,
        description="Filter rows based on conditions (>, <, =, contains, etc.)",
        estimated_cost=0.8,
        semantic_description="Filters dataframe rows by condition"
    ),
    Operator(
        name="SELECT_COLUMNS",
        category=OperatorType.FILTERING_EXTRACTION,
        description="Select subset of columns relevant to the query",
        estimated_cost=0.3,
        semantic_description="Selects specific columns from the dataframe"
    ),
    Operator(
        name="GROUP_BY",
        category=OperatorType.AGGREGATION,
        description="Group data by one or more columns",
        required_columns=[],
        produced_columns=["grouped_data"],
        estimated_cost=1.8,
        semantic_description="Groups data by specified columns for aggregation"
    ),
    Operator(
        name="AGGREGATE",
        category=OperatorType.AGGREGATION,
        description="Aggregate data: sum, mean, count, min, max, etc.",
        produced_columns=["aggregated_result"],
        estimated_cost=1.5,
        semantic_description="Performs aggregation operations on data"
    ),
    Operator(
        name="SORT_VALUES",
        category=OperatorType.FILTERING_EXTRACTION,
        description="Sort dataframe by one or more columns",
        estimated_cost=0.6,
        semantic_description="Sorts data by specified columns"
    ),
    Operator(
        name="DERIVE_COLUMN",
        category=OperatorType.TRANSFORMATION,
        description="Create new column via formula or calculation",
        produced_columns=["derived_column"],
        estimated_cost=1.0,
        semantic_description="Derives a new column from existing data"
    ),
    Operator(
        name="CLEAN_MISSING",
        category=OperatorType.DATA_CLEANING,
        description="Handle missing values: drop, fill, or impute",
        estimated_cost=1.2,
        semantic_description="Cleans missing or null values"
    ),
    Operator(
        name="JOIN_TABLES",
        category=OperatorType.MULTI_TABLE,
        description="Join two tables on common key",
        estimated_cost=2.5,
        semantic_description="Joins multiple tables together"
    ),
    Operator(
        name="VALIDATE",
        category=OperatorType.VALIDATION,
        description="Validate data quality or results",
        estimated_cost=0.5,
        semantic_description="Validates data integrity or correctness"
    ),
]

# Create lookup dict
OPERATOR_BY_NAME = {op.name: op for op in OPERATOR_POOL}


class ADOModule:
    """
    ADO Module - Operator Extraction via LLM
    
    This is the ONLY module that calls LLM for planning.
    Output is a SET of operators, not an ordered sequence.
    """
    
    def __init__(self, llm_client):
        """
        Args:
            llm_client: LLM client with call_api(prompt) -> str method
        """
        self.llm_client = llm_client
        self.operator_pool = OPERATOR_POOL
        self.operator_by_name = OPERATOR_BY_NAME
    
    def extract_operators(
        self,
        user_query: str,
        table_metadata: Dict[str, Any],
        smg_module=None,
        schema_result=None
    ) -> ADOResult:
        """
        Extract required operators for the query.
        
        ⭐ KEY IMPROVEMENT: 如果提供smg_module，会利用历史经验来改进operator选择
        ⭐ SCHEMA ENHANCEMENT: 如果提供schema_result，会利用Schema信息辅助选择
        
        Args:
            user_query: Natural language question
            table_metadata: Dict with keys: column_names, column_types, row_count, etc.
            smg_module: Optional SMGModule instance for accessing historical experience
            schema_result: Optional SchemaLinkingResult with selected headers and triplets
        
        Returns:
            ADOResult containing list of Operator objects
        """
        # Build prompt (with historical experience and schema if available)
        prompt = self._build_extraction_prompt(user_query, table_metadata, smg_module, schema_result)
        
        # Call LLM
        try:
            raw_response = self.llm_client.call_api(prompt)
        except Exception as e:
            # Fallback to default operators on LLM failure
            return self._get_default_operators(user_query, table_metadata, error=str(e))
        
        # Parse response
        operators = self._parse_operator_response(raw_response)
        
        if not operators:
            # Fallback if parsing failed
            return self._get_default_operators(user_query, table_metadata, error="Parsing failed")
        
        result = ADOResult(
            operators=operators,
            user_query=user_query,
            table_metadata=table_metadata,
            raw_llm_response=raw_response
        )
        
        return result
    
    def _build_extraction_prompt(
        self,
        user_query: str,
        table_metadata: Dict[str, Any],
        smg_module=None,
        schema_result=None
    ) -> str:
        """
        Build LLM prompt for operator extraction.
        
        ⭐ KEY: 如果提供smg_module，会在prompt中包含历史经验
        ⭐ SCHEMA: 如果提供schema_result，会在prompt中包含Schema三元组
        """
        
        # Operator catalog
        catalog_lines = ["Available Operators:\n"]
        for op in self.operator_pool:
            catalog_lines.append(f"- {op.name}: {op.description}")
        catalog = "\n".join(catalog_lines)
        
        # ⭐ ENHANCED: 提供完整的表格信息（前100行sample + meta信息）
        columns = table_metadata.get("column_names", [])
        column_types = table_metadata.get("column_types", {})
        row_count = table_metadata.get("row_count", "unknown")
        
        # 获取sample data（前100行）
        sample_data_section = ""
        if "sample_data" in table_metadata and table_metadata["sample_data"] is not None:
            import pandas as pd
            sample_df = table_metadata["sample_data"]
            if isinstance(sample_df, pd.DataFrame) and not sample_df.empty:
                preview_rows = min(100, len(sample_df))
                sample_data_section = f"""
## Table Sample Data (first {preview_rows} rows):
{sample_df.head(preview_rows).to_string()}

## Column Statistics:
{sample_df.describe(include='all').to_string()}
"""
        
        table_summary = f"""Table Information:
- Shape: {row_count} rows × {len(columns)} columns
- Columns: {', '.join(columns[:30])}
- Sample column types: {', '.join([f'{k}:{v}' for k, v in list(column_types.items())[:15]])}
{sample_data_section}"""
        
        # ⭐ ENHANCED: 添加详细的meta信息
        meta_section = ""
        meta_info = table_metadata.get("meta_info")
        if meta_info and not meta_info.get("error"):
            meta_lines = []
            meta_lines.append("\n## Table Structure (Meta Information - IMPORTANT!):")
            
            # Header levels
            header_levels = meta_info.get("header_levels", 0)
            if header_levels > 1:
                meta_lines.append(f"- **Multi-level headers detected**: {header_levels} levels")
            
            # Merged cells
            merged_cells = meta_info.get("merged_cells", [])
            if merged_cells:
                meta_lines.append(f"- ⚠️  **Contains {len(merged_cells)} merged cells** (complex structure!)")
                meta_lines.append("  → You MUST use DETECT_SCHEMA first to understand the structure")
                meta_lines.append("  → Consider INSPECT_COLUMN to explore data before operations")
            
            # Hierarchy triplets
            triplets = meta_info.get("hierarchy_triplets", [])
            if triplets:
                meta_lines.append(f"\n### Hierarchical Structure ({len(triplets)} relationships):")
                for triplet in triplets[:10]:
                    meta_lines.append(f"  {triplet}")
            
            meta_section = "\n".join(meta_lines) + "\n"
        
        # ⭐ 获取历史经验摘要（如果可用）
        experience_section = ""
        if smg_module:
            experience_summary = smg_module.get_experience_summary_for_llm(max_entries=5)
            if experience_summary:
                experience_section = f"""
# Historical Experience (learn from past executions):
{experience_summary}

**IMPORTANT**: Consider this experience when selecting operators:
- Prefer operators with high success rates
- If an operator often fails, consider adding preprocessing steps (e.g., CLEAN_MISSING, VALIDATE_DATA)
- Follow the suggestions to avoid common failure patterns

"""
        
        # ⭐ 添加Schema信息（如果可用）
        schema_section = ""
        if schema_result:
            schema_lines = []
            schema_lines.append("\n# Schema Linking Information (Header Relationships):")
            schema_lines.append("The system has identified relevant table headers for this query:")
            
            if schema_result.selected_row_headers:
                schema_lines.append(f"\n**Relevant Row Headers** ({len(schema_result.selected_row_headers)}):")
                for header in schema_result.selected_row_headers[:10]:
                    schema_lines.append(f"  - {header}")
            
            if schema_result.selected_col_headers:
                schema_lines.append(f"\n**Relevant Column Headers** ({len(schema_result.selected_col_headers)}):")
                for header in schema_result.selected_col_headers[:10]:
                    schema_lines.append(f"  - {header}")
            
            if schema_result.triplets:
                schema_lines.append(f"\n**Header Relationships** ({len(schema_result.triplets)} triplets):")
                for triplet in schema_result.triplets[:8]:
                    schema_lines.append(f"  {triplet}")
                schema_lines.append("\n**Guidance**: These relationships show how headers are connected.")
                schema_lines.append("  Use this to understand the data structure when selecting operators.")
            
            schema_lines.append(f"\n**Confidence**: {schema_result.confidence:.2f}")
            schema_lines.append("")
            
            schema_section = "\n".join(schema_lines)
        
        prompt = f"""You are an expert data analyst. Given a user query and table metadata, identify which operators are needed.

{catalog}

{table_summary}

{meta_section}

{schema_section}

{experience_section}

User Query: {user_query}

CRITICAL INSTRUCTIONS:
1. Output a SET of operator names (NOT ordered sequence)
2. Only include operators that are NECESSARY for answering the query
3. Output ONLY valid JSON in this exact format:
{{
  "operators": ["OPERATOR_NAME_1", "OPERATOR_NAME_2", ...],
  "reasoning": "brief explanation of why these operators are needed"
}}

4. Operator names must be EXACTLY as listed above (e.g., "GROUP_BY", not "group_by")
5. Do NOT include execution order or dependencies
6. Do NOT include unnecessary operators
7. **If historical experience suggests preprocessing (e.g., validation, cleaning), include those operators**

Example for "What is the average salary by department?":
{{
  "operators": ["GROUP_BY", "AGGREGATE", "SELECT_COLUMNS"],
  "reasoning": "Need to group by department, aggregate salaries, and select relevant columns"
}}

Output JSON:
"""
        return prompt
    
    def _parse_operator_response(self, raw_response: str) -> List[Operator]:
        """Parse LLM response and extract operators"""
        
        # Try to extract JSON
        data = self._extract_json(raw_response)
        
        if not data or "operators" not in data:
            return []
        
        operator_names = data["operators"]
        
        # Validate and convert to Operator objects
        operators = []
        for name in operator_names:
            if name in self.operator_by_name:
                operators.append(self.operator_by_name[name])
            else:
                # Try case-insensitive match
                for op_name, op in self.operator_by_name.items():
                    if op_name.lower() == name.lower():
                        operators.append(op)
                        break
        
        return operators
    
    def _extract_json(self, text: str) -> Optional[Dict]:
        """Extract JSON from text (handles markdown code blocks)"""
        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        
        # Try to find JSON in markdown code blocks
        json_match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        
        # Try to find any JSON object
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass
        
        return None
    
    def _get_default_operators(
        self,
        user_query: str,
        table_metadata: Dict[str, Any],
        error: str = ""
    ) -> ADOResult:
        """Return default operator set as fallback"""
        
        # Simple heuristic-based selection
        operators = []
        
        query_lower = user_query.lower()
        
        # Always start with schema detection
        operators.append(self.operator_by_name["DETECT_SCHEMA"])
        
        # Check for aggregation keywords
        if any(kw in query_lower for kw in ["average", "sum", "total", "count", "mean", "max", "min"]):
            operators.append(self.operator_by_name["AGGREGATE"])
        
        # Check for grouping keywords
        if any(kw in query_lower for kw in ["by", "each", "per", "group"]):
            operators.append(self.operator_by_name["GROUP_BY"])
        
        # Check for filtering keywords
        if any(kw in query_lower for kw in ["where", "filter", "only", "greater than", "less than", "equal"]):
            operators.append(self.operator_by_name["FILTER_ROWS"])
        
        # Check for sorting keywords
        if any(kw in query_lower for kw in ["sort", "order", "rank", "top", "bottom"]):
            operators.append(self.operator_by_name["SORT_VALUES"])
        
        # Always include column selection for efficiency
        operators.append(self.operator_by_name["SELECT_COLUMNS"])
        
        # If no specific operators found, add inspection
        if len(operators) <= 2:
            operators.append(self.operator_by_name["INSPECT_COLUMN"])
        
        result = ADOResult(
            operators=operators,
            user_query=user_query,
            table_metadata=table_metadata,
            raw_llm_response=f"Fallback mode (error: {error})"
        )
        
        return result
    


def test_ado_module():
    """Test ADO module with mock LLM"""
    class MockLLM:
        def call_api(self, prompt):
            return '''```json
{
  "operators": ["GROUP_BY", "AGGREGATE", "SORT_VALUES"],
  "reasoning": "Group by department, aggregate salaries, then sort"
}
```'''
    
    llm = MockLLM()
    ado = ADOModule(llm)
    
    result = ado.extract_operators(
        user_query="What is the average salary by department, sorted descending?",
        table_metadata={
            "column_names": ["employee_id", "name", "department", "salary"],
            "column_types": {"employee_id": "int", "name": "str", "department": "str", "salary": "float"},
            "row_count": 100
        }
    )
    
    print(f"ADO Result: {result}")
    print(f"Operators extracted: {[op.name for op in result.operators]}")
    for op in result.operators:
        print(f"  - {op}")
    
    return result


if __name__ == "__main__":
    test_ado_module()

