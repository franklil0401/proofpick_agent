"""
Answer Generator Module - 通用答案生成器
从执行结果生成符合要求的自然语言答案
"""

import pandas as pd
from typing import Any, Dict, Optional
import re
import logging
import os
import sys

# 导入baseline的prompt模板
try:
    # 添加benchmarks路径到sys.path
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(script_dir)))
    benchmarks_path = os.path.join(project_root, 'benchmarks', 'realhitbench', 'eval', 'inference')
    if benchmarks_path not in sys.path:
        sys.path.insert(0, benchmarks_path)
    
    from answer_prompt_llm import Answer_Prompt
    PROMPT_TEMPLATES_AVAILABLE = True
except ImportError as e:
    PROMPT_TEMPLATES_AVAILABLE = False
    Answer_Prompt = {}

# 导入Data Analysis详细prompts
try:
    from src.config.data_analysis_prompts import (
        RUDIMENTARY_EXPLORATORY_PROMPT,
        SUMMARY_ANALYSIS_PROMPT,
        ANOMALY_ANALYSIS_PROMPT,
        PREDICTIVE_ANALYSIS_PROMPT
    )
    DATA_ANALYSIS_PROMPTS_AVAILABLE = True
except ImportError:
    DATA_ANALYSIS_PROMPTS_AVAILABLE = False
    RUDIMENTARY_EXPLORATORY_PROMPT = ""
    SUMMARY_ANALYSIS_PROMPT = ""
    ANOMALY_ANALYSIS_PROMPT = ""
    PREDICTIVE_ANALYSIS_PROMPT = ""


class AnswerGenerator:
    """通用答案生成器 - 将DataFrame结果转换为简洁的自然语言答案"""
    
    def __init__(self, llm_client):
        self.llm_client = llm_client
        self.logger = logging.getLogger(__name__)
    
    def generate_answer(
        self,
        user_query: str,
        result_df: pd.DataFrame,
        execution_trace: list = None,
        question_type: str = "",
        sub_q_type: str = "",
        all_path_results: list = None,
        original_df: pd.DataFrame = None,
        enable_reflection: bool = False,  # ⭐ 禁用迭代反思（性能下降10.75 points）
        markdown_table: str = None,  # ⭐ Schema增强: 过滤后的markdown表格
        schema_result = None  # ⭐ Schema增强: Schema Linking结果
    ) -> str:
        """
        生成最终答案（基于所有paths的结果）
        
        V8.1增强: 支持迭代反思推理（Iterative Reflection）
        - Round 1: 生成初步答案
        - Round 2: 验证并改进答案（检查数字、格式、完整性）
        
        Schema增强: 使用markdown_table和schema_result验证答案准确性
        
        Args:
            user_query: 用户问题
            result_df: 最佳path的执行结果DataFrame
            execution_trace: 执行轨迹
            question_type: 问题类型
            all_path_results: 所有paths的结果（用于综合判断）
            original_df: 原始表格数据（前100行）
            enable_reflection: 是否启用迭代反思（默认True，建议对短答案类型启用）
            markdown_table: 过滤后的markdown格式表格（来自Schema Linking）
            schema_result: Schema Linking结果（包含选中的行列headers）
            
        Returns:
            格式化答案: "[Final Answer]: <answer>"
        """
        
        # 空结果处理 - 改进：先尝试从原始数据中提取答案
        if result_df is None or result_df.empty:
            # 如果原始数据存在，尝试从原始数据中提取答案
            if original_df is not None and not original_df.empty:
                self.logger.warning("Result DataFrame is empty, attempting to extract answer from original data")
                # 尝试从原始数据中提取简单答案
                fallback_answer = self._try_extract_from_original(user_query, original_df, question_type)
                if fallback_answer and "no data" not in fallback_answer.lower():
                    return fallback_answer
            return "[Final Answer]: No data available"
        
        # ⭐ 检测是否为短答案类型（Fact Checking, Numerical Reasoning, Structure Comprehending）
        is_short_answer_type = self._is_short_answer_type(question_type, sub_q_type)
        
        # ==================== Round 1: 初步答案生成 ====================
        self.logger.info("📝 Answer Generation: Round 1 - Initial answer...")
        
        # 构建prompt（包含所有paths的结果和原始数据）
        prompt_round1 = self._build_prompt(
            user_query, 
            result_df, 
            question_type,
            sub_q_type=sub_q_type,
            all_path_results=all_path_results,
            original_df=original_df,
            use_concise_mode=is_short_answer_type,  # ⭐ 传递短答案模式标志
            markdown_table=markdown_table,  # ⭐ Schema增强
            schema_result=schema_result  # ⭐ Schema增强
        )
        
        try:
            # Round 1: 调用LLM生成初步答案
            raw_answer_round1 = self.llm_client.call_api(prompt_round1)
            
            # 清理并格式化
            formatted_round1 = self._format_answer(raw_answer_round1, is_short_answer=is_short_answer_type)
            
            # 如果不启用反思，直接返回
            if not enable_reflection:
                self.logger.info("✅ Answer generated (no reflection)")
                return formatted_round1
            
            # 对于长答案类型（Data Analysis, Visualization），跳过反思（避免过度优化）
            if not is_short_answer_type:
                self.logger.info("✅ Answer generated (long-form, skipping reflection)")
                return formatted_round1
            
            # ==================== Round 2: 迭代反思与验证 ====================
            self.logger.info("🔄 Answer Generation: Round 2 - Reflection and verification...")
            
            # 提取纯答案（移除[Final Answer]:标记）
            clean_answer_round1 = formatted_round1.replace("[Final Answer]:", "").strip()
            
            prompt_round2 = f"""You previously answered a question. Now verify and improve your answer.

**Original Question**: {user_query}
**Question Type**: {question_type}

**Your Previous Answer**: {clean_answer_round1}

**Execution Result**:
{self._format_dataframe(result_df, max_rows=20, use_markdown=True)}

**Original Table Data (for verification)**:
{self._format_dataframe(original_df.head(50), max_rows=50, use_markdown=True) if original_df is not None else "Not available"}

---

**VERIFICATION CHECKLIST** (⭐ CRITICAL - Check each item):

1. **Data Extraction Accuracy**
   - □ Did I extract data from the CORRECT row(s)?
   - □ Did I use the CORRECT column(s)?
   - □ Are the numbers EXACTLY matching the table?
   - □ Did I confuse similar column names (e.g., "Total employed" vs "Employed total")?

2. **Calculation Accuracy** (if applicable)
   - □ Is my arithmetic correct? (Re-calculate: sum, average, max, min)
   - □ Did I include/exclude the right rows? (Check for "Total", "Sum", "Average" rows)
   - □ Did I apply the right formula?

3. **Number Format Consistency**
   - □ Integers: No decimal point (e.g., 1955, 62170, NOT 1955.0)
   - □ Two-decimal numbers: Always .XX format (e.g., 43.60, 0.70, NOT 43.6 or 0.7)
   - □ Remove thousand separators (99826, NOT 99,826)

4. **Answer Completeness**
   - □ Did I answer ALL parts of the question?
   - □ If multiple values requested, did I use comma-separated format? (e.g., "1955, 62170")

5. **Answer Brevity (SHORT ANSWER MODE)**
   - □ Is this a Fact Checking / Numerical Reasoning question? → Output ONLY the answer
   - □ NO explanations like "The answer is...", "Based on the data..."
   - □ NO context like "Men are larger than women", just output "Men"
   - □ Examples:
     * Good: "Men" | Bad: "Men (85500) are larger in number than women (75537)"
     * Good: "1955, 62170" | Bad: "The year with max was 1955 with population 62170"
     * Good: "Yes" | Bad: "Yes, the value is higher"

6. **Edge Cases**
   - □ If answer not found in data, say "Cannot be determined" (NOT "No such year exists")
   - □ For Yes/No questions, answer ONLY "Yes" or "No"

---

**INSTRUCTIONS**:
1. Review your previous answer against the checklist above
2. If you found ANY errors or formatting issues, OUTPUT the CORRECTED answer
3. If your previous answer is perfect, OUTPUT it again unchanged
4. Format: "[Final Answer]: <your verified/corrected answer>"

**IMPORTANT**: Output ONLY the final answer line, no explanations about what you changed!

Output:"""
            
            # Round 2: 调用LLM进行反思和验证
            raw_answer_round2 = self.llm_client.call_api(prompt_round2)
            
            # 清理并格式化
            formatted_round2 = self._format_answer(raw_answer_round2, is_short_answer=is_short_answer_type)
            
            self.logger.info("✅ Answer refined through reflection")
            return formatted_round2
            
        except Exception as e:
            self.logger.error(f"Answer generation failed: {e}")
            # Fallback: 简单拼接DataFrame的值
            fallback = self._generate_fallback(result_df)
            return f"[Final Answer]: {fallback}"
    
    def _build_prompt(
        self, 
        user_query: str, 
        result_df: pd.DataFrame, 
        question_type: str,
        sub_q_type: str = "",
        all_path_results: list = None,
        original_df: pd.DataFrame = None,
        use_concise_mode: bool = False,  # ⭐ 新增：短答案模式
        markdown_table: str = None,  # ⭐ Schema增强：过滤后的markdown表格
        schema_result = None  # ⭐ Schema增强：Schema Linking结果
    ) -> str:
        """构建答案生成prompt（包含所有paths的结果和原始数据）
        
        Schema增强: 使用markdown_table提供更清晰的数据视图，
                    使用schema_result提示相关的headers
        """
        
        # DataFrame格式化（最佳path的结果）
        df_str = self._format_dataframe(result_df, max_rows=20)
        
        # 尝试使用baseline的prompt模板
        prompt_template = None
        answer_format = "AnswerName1, AnswerName2..."
        
        if PROMPT_TEMPLATES_AVAILABLE and question_type:
            # 根据问题类型和子类型选择prompt模板
            if question_type == "Data Analysis" and sub_q_type:
                # Data Analysis根据SubQType选择
                prompt_template = Answer_Prompt.get(sub_q_type)
                if not prompt_template:
                    prompt_template = Answer_Prompt.get("Rudimentary Analysis", Answer_Prompt.get("Fact Checking"))
            elif question_type in Answer_Prompt:
                prompt_template = Answer_Prompt.get(question_type)
            
            # 设置答案格式
            if sub_q_type == "Exploratory Analysis":
                answer_format = "CorrelationRelation, CorrelationCoefficient"
            elif question_type == "Visualization":
                answer_format = "Python code"
            elif question_type == "Summary Analysis":
                answer_format = "TableSummary"
            elif question_type == "Anomaly Analysis":
                answer_format = "Conclusion"
        
        # 添加原始数据（前100行）
        original_data_section = ""
        if original_df is not None and not original_df.empty:
            # ⭐ Schema增强：优先使用markdown_table（已过滤相关列）
            if markdown_table:
                original_data_section = "\n# Relevant Table Data (filtered by Schema Linking):\n"
                original_data_section += markdown_table
                original_data_section += "\n**NOTE**: This table has been filtered to show only relevant columns/rows based on the query.\n"
            else:
                original_data_section = "\n# Original Table Data (first 100 rows for context):\n"
                original_data_section += self._format_dataframe(original_df.head(100), max_rows=100)
                original_data_section += "\n**NOTE**: Use this to understand the data structure and verify the result. Pay attention to special indicators such as 'Total', 'Sum', 'Average', 'Mean', etc. in row/column headers.\n"
        
        # ⭐ Schema增强：添加Schema信息提示
        schema_hint = ""
        if schema_result:
            schema_lines = []
            schema_lines.append("\n# Schema Information (Relevant Headers):")
            
            if schema_result.selected_col_headers:
                schema_lines.append(f"**Relevant Columns** ({len(schema_result.selected_col_headers)}): {', '.join(schema_result.selected_col_headers[:10])}")
            
            if schema_result.selected_row_headers:
                schema_lines.append(f"**Relevant Rows** ({len(schema_result.selected_row_headers)}): {', '.join(schema_result.selected_row_headers[:10])}")
            
            schema_lines.append("**Guidance**: Focus on these headers when extracting the answer.\n")
            schema_hint = "\n".join(schema_lines)
        
        # 添加所有paths的结果对比
        all_paths_section = ""
        if all_path_results and len(all_path_results) > 1:
            all_paths_section = "\n# All Execution Paths Results:\n"
            for idx, path_result in enumerate(all_path_results[:3], 1):  # 最多显示3个
                path_df = path_result.get('final_df')
                if path_df is not None and not path_df.empty:
                    all_paths_section += f"\nPath {idx} ({path_result.get('path_id', 'Unknown')}):\n"
                    all_paths_section += f"  Success Rate: {path_result.get('success_count', 0)}/{path_result.get('total_ops', 0)}\n"
                    all_paths_section += f"  Reward: {path_result.get('cumulative_reward', 0):.1f}\n"
                    all_paths_section += f"  Result:\n"
                    all_paths_section += self._format_dataframe(path_df, max_rows=3)
                    all_paths_section += "\n"
            
            all_paths_section += "\n**NOTE**: Multiple paths shown for verification only. Output ONE answer based on the Best Path Result.\n"
        
        # 如果使用了baseline的prompt模板，构建完整prompt
        if prompt_template:
            # 分析问题意图
            question_analysis = self._analyze_question_intent(user_query)
            
            # ⭐ 短答案类型：使用简洁模式Prompt
            if use_concise_mode:
                # 子类型特殊处理
                calculation_guidance = ""
                if sub_q_type in ["Ranking", "Comparison"]:
                    calculation_guidance = """
**RANKING/COMPARISON CRITICAL INSTRUCTIONS:**
1. EXTRACT ALL relevant items with their numeric values from the Execution Result
2. SORT them correctly by the metric (ascending/descending based on question keywords)
   - "highest", "top", "largest", "most" → descending order (largest first)
   - "lowest", "bottom", "smallest", "least" → ascending order (smallest first)
3. COUNT how many items are requested ("top 3", "top 5", "highest 2", etc.)
4. OUTPUT ONLY those top N items in the correct order
5. FORMAT: "Item1, Item2, Item3" (comma-separated, item names ONLY, NO values, NO parentheses)

**CRITICAL EXAMPLE**:
Question: "List the top 3 products by sales (highest to lowest)."
Execution Result: Product A (100), Product B (200), Product C (150), Product D (80)
Step 1: Extract all → [(B, 200), (C, 150), (A, 100), (D, 80)]
Step 2: Already sorted (highest first) → B > C > A > D
Step 3: Take top 3 → B, C, A
[Final Answer]: Product B, Product C, Product A

⚠️ COMMON MISTAKES TO AVOID:
- ❌ Including values: "Product B (200), Product C (150)" → ✅ "Product B, Product C"
- ❌ Wrong order: Starting with smallest when question asks for "highest"
- ❌ Wrong count: Outputting 5 items when question asks for "top 3"
- ❌ Including all items: Must limit to requested count!
"""
                elif sub_q_type == "Counting":
                    calculation_guidance = """
**COUNTING SPECIAL INSTRUCTIONS:**
1. Look for a count/total value in the Execution Result
2. If multiple groups exist, sum them if question asks for "total" or "combined"
3. Output ONLY the number (no units, no explanations)
"""
                elif sub_q_type in ["Inference-based Fact Checking", "Multi-hop Fact Checking"]:
                    calculation_guidance = """
**FACT CHECKING SPECIAL INSTRUCTIONS:**
1. For calculation questions: Perform the calculation step-by-step mentally, then output only the result
2. For Yes/No questions: Check the condition carefully (>, >=, <, <=, =)
3. For "find year when X" questions: Scan ALL rows in Original Table Data
4. Output: For Yes/No → "Yes" or "No", For numbers → the value, For year/text → the exact value
"""
                
                prompt = f"""{prompt_template}

# Table
{original_data_section}
{schema_hint}
# Execution Result (after processing):
{df_str}
{all_paths_section}

# Question Analysis
{question_analysis}

{calculation_guidance}

# ⭐⭐⭐ CRITICAL: SHORT ANSWER MODE - NO EXPLANATIONS ALLOWED ⭐⭐⭐
**IMPORTANT: This is a SHORT ANSWER question. You MUST output ONLY the value, NO steps, NO reasoning.**

**STRICT FORMAT REQUIREMENT:**
```
[Final Answer]: <value>
```

**RULES (MUST FOLLOW):**
1. **Output ONLY the answer value** - No "To find..." or "Follow these steps..."
2. **Extract from Execution Result OR Original Table Data**:
   - Single value → Just the value (e.g., "1955")
   - Multiple values → Comma-separated (e.g., "1955, 62170")
   - Yes/No → "Yes" or "No" only
3. **Number format**: Remove commas (99,826 → 99826), keep 2 decimals if float
4. **Calculation accuracy**: If you need to calculate average/sum/etc., do it precisely
5. **Boundary checks**: For comparisons, distinguish > vs >= carefully
6. **NO explanations** - The answer line should be THE ONLY line you output

**EXAMPLES OF CORRECT OUTPUT:**
- [Final Answer]: 1955
- [Final Answer]: 158772
- [Final Answer]: 1955, 62170
- [Final Answer]: Yes
- [Final Answer]: 35 to 39 years, 40 to 44 years

**EXAMPLES OF WRONG OUTPUT (DO NOT DO THIS):**
- ❌ "To find the answer, first identify... [Final Answer]: 1955"
- ❌ "From the table, the value is 1955. [Final Answer]: 1955"
- ❌ "The answer is 1955 because..."

**NOW OUTPUT ONLY THE ANSWER LINE:**

# Question
{user_query}

Output format: [Final Answer]: {answer_format}
"""
            else:
                # 长答案类型：使用完整分析模式
                # 根据问题类型添加特殊指导
                type_specific_guidance = ""
                
                # ⭐⭐⭐ 重要：只有Data Analysis类型需要详尽分析，其他类型简洁输出 ⭐⭐⭐
                
                if question_type == "Visualization":
                    type_specific_guidance = """
# ⭐⭐⭐ VISUALIZATION: OUTPUT EXECUTABLE PYTHON CODE ONLY ⭐⭐⭐

**THIS IS A CODE GENERATION TASK - Your output will be executed by Python**

**MANDATORY CODE STRUCTURE:**
```python
import pandas as pd
import matplotlib.pyplot as plt

# 1. Load data
df = pd.read_excel('filename.xlsx')

# 2. Process data (CRITICAL: Ensure correct columns and aggregations)
#    Example: df_plot = df.groupby('Category')['Value'].sum()

# 3. Create visualization
plt.figure(figsize=(10, 6))
# For Pie Chart: plt.pie(values, labels=labels, autopct='%1.1f%%')
# For Bar Chart: plt.bar(x, y)
# For Line Chart: plt.plot(x, y, marker='o')
plt.title('Title Here')
plt.xlabel('X Label')
plt.ylabel('Y Label')
plt.show()
```

**CRITICAL DATA PROCESSING RULES:**
1. **Column Selection**: Use EXACT column names from Original Table Data
2. **Aggregation**: If needed, use groupby().sum() / groupby().mean() / etc.
3. **Filtering**: Remove non-data rows (headers, totals) if present
4. **Data Validation**: Ensure values are numeric (use pd.to_numeric if needed)

**CHART TYPE REQUIREMENTS:**
- **Pie Chart**: Must have values (sizes) and labels
- **Bar Chart**: Must have x-axis categories and y-axis values
- **Line Chart**: Must have x-axis points and y-axis values
- **Scatter Plot**: Must have x and y coordinates

**FORBIDDEN OUTPUTS:**
❌ "To create a chart, ..." (NO explanations!)
❌ "Here is the code..." (NO descriptions!)
❌ "Follow these steps..." (NO instructions!)

**REMEMBER**: The evaluator will extract Y-axis data from your plot. Ensure data is correctly processed!
"""
                elif question_type == "Data Analysis":
                    if sub_q_type in ["Rudimentary Analysis", "Exploratory Analysis"]:
                        type_specific_guidance = RUDIMENTARY_EXPLORATORY_PROMPT if DATA_ANALYSIS_PROMPTS_AVAILABLE else """
# ⭐ DATA ANALYSIS: PROVIDE COMPREHENSIVE ANALYSIS ⭐

**YOU MUST PROVIDE DETAILED ANALYSIS, NOT JUST NUMBERS**

Include: Data overview, calculation process, statistical details, insights, and context.
"""
                    elif sub_q_type == "Summary Analysis":
                        type_specific_guidance = SUMMARY_ANALYSIS_PROMPT if DATA_ANALYSIS_PROMPTS_AVAILABLE else """
# ⭐ SUMMARY ANALYSIS: PROVIDE COMPREHENSIVE TABLE DESCRIPTION ⭐

Include: Table structure, column descriptions, key insights & trends, statistical highlights.
"""
                    elif sub_q_type == "Anomaly Analysis":
                        type_specific_guidance = ANOMALY_ANALYSIS_PROMPT if DATA_ANALYSIS_PROMPTS_AVAILABLE else """
# ⭐ ANOMALY ANALYSIS: IDENTIFY AND EXPLAIN ALL ANOMALIES ⭐

Include: Detection methodology, identified anomalies with details, root cause analysis, patterns.
"""
                    elif sub_q_type == "Predictive Analysis":
                        type_specific_guidance = PREDICTIVE_ANALYSIS_PROMPT if DATA_ANALYSIS_PROMPTS_AVAILABLE else """
# ⭐ PREDICTIVE ANALYSIS: SHOW PREDICTION METHODOLOGY ⭐

Include: Historical analysis, prediction methodology, calculation steps, predicted value, validation.
"""
                    else:
                        type_specific_guidance = """
# ⭐ DATA ANALYSIS: PROVIDE THOROUGH ANALYSIS ⭐

For any data analysis, include comprehensive explanation with calculations, insights, and context.
"""
                
                prompt = f"""{prompt_template}

# Table
{original_data_section}
{schema_hint}
# Execution Result (after processing):
{df_str}
{all_paths_section}

# Question Analysis
{question_analysis}

{type_specific_guidance}

# Critical Instructions for Answer Extraction:
1. **Read the question CAREFULLY** - Identify what is being asked:
   - Is it asking for a maximum/minimum value? → Extract the max/min value
   - Is it asking for a specific year/date? → Extract that specific value
   - Is it asking for a count? → Extract the count number
   - Is it asking for multiple values? → Extract all requested values
   - Is it a Yes/No question? → Analyze and answer 'Yes' or 'No'
   - Is it asking for visualization? → Output Python code!

2. **Examine the Execution Result carefully**:
   - If result has 1 row: Extract the relevant value(s) from that row
   - If result has multiple rows: 
     * For max/min questions: Find the row with max/min value and extract it
     * For list questions: Extract all relevant values
     * For count questions: Count the rows or extract the count value
   - If result is empty: Check Original Table Data for direct answer

3. **Check Original Table Data for special indicators**:
   - Look for rows labeled "Total", "Sum", "Average", "Mean"
   - Look for hierarchical groupings (age groups, categories)
   - Understand the table structure before extracting values

4. **Verify your answer**:
   - Does it directly answer the question?
   - Are you extracting the correct column(s)?
   - Are you using the right row(s)?
   - For calculations: Are your numbers accurate?

# Critical Format Rules (MUST FOLLOW):
1. The answer MUST start with '[Final Answer]: '

2. **OUTPUT LENGTH DEPENDS ON QUESTION TYPE** (CRITICAL - READ CAREFULLY):
   
   ⭐ **FOR DATA ANALYSIS QUESTIONS ONLY** (Rudimentary/Exploratory/Summary/Anomaly/Predictive Analysis):
   - Provide COMPREHENSIVE, DETAILED analysis as specified above
   - Include: Data overview, calculation process, statistical details, insights, context
   - Expected length: 300-700 words with multiple sections
   
   ❌ **FOR ALL OTHER QUESTION TYPES** (Fact Checking, Numerical Reasoning, Comparison, Ranking, etc.):
   - Extract ONLY the final answer value
   - NO explanations, NO analysis, NO reasoning steps
   - Expected length: One line - just "[Final Answer]: <value>"
   
3. **Number formatting**:
   - Remove all thousand separators (commas) from numbers (e.g., 99,826 -> 99826)
   - For numerical answers, keep consistent decimal places (2 decimals for floats)
   
4. **Special answer types**:
   - For Yes/No questions: answer ONLY 'Yes' or 'No'
   - For Visualization questions: Output ONLY executable Python code (no descriptions)
   
5. **Answer accuracy**: Use the original format from the table without modifying it

# Question
{user_query}

Emphasize: you need to make sure your final answer is formatted in this way: [Final Answer]: {answer_format}
"""
        else:
            # 使用通用prompt（fallback）
            type_hint = ""
            if question_type:
                type_hint = f"Question Type: {question_type}\n"
                if sub_q_type:
                    type_hint += f"Sub Type: {sub_q_type}\n"
                
                # 可视化类型特殊处理
                if question_type == "Visualization":
                    type_hint += """
**⭐⭐⭐ CRITICAL for Visualization questions - OUTPUT CODE, NOT DESCRIPTION! ⭐⭐⭐**
- You MUST output EXECUTABLE Python code, NOT natural language description
- Use matplotlib or seaborn
- Include necessary imports (import pandas as pd, import matplotlib.pyplot as plt)
- Load data from the Excel file mentioned in the question
- Create the requested visualization
- Include title, labels, and legend
- End with plt.show()
- DO NOT output "To create a chart..." - OUTPUT THE CODE!

Example format:
```python
import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_excel('employment-table02.xlsx')
# ... data processing ...
plt.figure(figsize=(10, 6))
plt.pie(values, labels=labels, autopct='%1.1f%%')
plt.title('...')
plt.show()
```
"""
                elif question_type == "Numerical Reasoning" and sub_q_type == "Ranking":
                    type_hint += """
**IMPORTANT for Ranking questions**:
1. Extract ALL candidate items with their values from the data
2. Sort them by the metric specified in the question
3. Output ONLY the requested number of items (top 2, top 5, etc.)
4. Format: "Item1, Item2, Item3" (comma-separated, item names only, no values)
5. Check the question carefully for "top", "highest", "descending" etc.
"""
            
            # 分析问题意图
            question_analysis = self._analyze_question_intent(user_query)
            
            # ⭐ 短答案类型：使用简洁模式
            if use_concise_mode:
                # 子类型特殊指导
                special_guidance = ""
                if sub_q_type in ["Ranking", "Comparison"]:
                    special_guidance = """
**RANKING/COMPARISON CRITICAL INSTRUCTIONS:**
1. EXTRACT ALL items with numeric values from data
2. SORT correctly: "highest/top/most" → descending, "lowest/bottom/least" → ascending
3. COUNT requested items: "top 3" = 3 items, "top 5" = 5 items
4. OUTPUT only top N in correct order
5. FORMAT: "Item1, Item2, Item3" (NO values, NO parentheses)

Example:
Q: "Top 3 regions by population (highest first)"
Data: North (100), South (200), East (150), West (80)
Answer: [Final Answer]: South, East, North
"""
                elif sub_q_type == "Counting":
                    special_guidance = """
**COUNTING INSTRUCTIONS:**
1. Look for count/sum in Execution Result or Original Table
2. If multiple groups, sum them if question says "total" or "all"
3. Output ONLY the number (no text)
"""
                elif sub_q_type in ["Inference-based Fact Checking", "Multi-hop Fact Checking"]:
                    special_guidance = """
**FACT CHECKING INSTRUCTIONS:**
1. For calculations: Compute precisely (sum/count for average, etc.)
2. For Yes/No: Check conditions carefully (>, >=, <, <=, =)
3. For "find when X": Scan ALL rows in Original Table Data
4. For boundary checks: 4.52% is NOT greater than 5% (use exact comparison)
"""
                
                prompt = f"""You are answering a SHORT ANSWER data query.

User Question: {user_query}
{type_hint}
{original_data_section}
{schema_hint}
# Execution Result (after processing):
{df_str}
{all_paths_section}

# Question Analysis
{question_analysis}

{special_guidance}

⭐⭐⭐ SHORT ANSWER MODE - CRITICAL ⭐⭐⭐
**You MUST output ONLY "[Final Answer]: <value>" with NO explanations.**

**STRICT RULES:**
1. **NO steps, NO reasoning, NO "To find..."** - Output ONLY the answer line
2. Extract from Execution Result OR Original Table Data:
   - Single value → Output value only
   - Multiple values → Comma-separated
   - Yes/No → "Yes" or "No" only
3. **Number Format (CRITICAL for scoring)**:
   - Integers: NO decimal point (e.g., 1955, 62170, NOT 1955.0)
   - Two-decimal numbers: Always .XX format (e.g., 43.60, 0.70, NOT 43.6 or 0.7)
   - Remove commas: 99,826 → 99826
   - Percentages: Two decimals (e.g., 12.50%)
4. Calculation accuracy: If computing average/sum, do it precisely
5. Boundary checks: Distinguish > vs >= carefully
6. **THE ANSWER LINE SHOULD BE YOUR ENTIRE OUTPUT**

**CORRECT OUTPUT:**
[Final Answer]: 1955

**WRONG OUTPUT (DO NOT DO THIS):**
To find the answer... [Final Answer]: 1955

**NOW OUTPUT ONLY THE ANSWER:**
"""
            else:
                # 长答案类型：使用完整prompt
                special_guidance = ""
                if question_type == "Visualization":
                    special_guidance = """
**⭐ VISUALIZATION: OUTPUT CODE, NOT DESCRIPTION ⭐**
You MUST output EXECUTABLE Python code!
"""
                elif question_type == "Data Analysis":
                    special_guidance = """
**⭐ DATA ANALYSIS: CHECK CALCULATIONS CAREFULLY ⭐**
- Verify mean, std, correlation calculations
- Check if you're using the correct data rows
- Look for special indicators in Original Table Data
"""
                
                prompt = f"""You are answering a data query based on execution results.

User Question: {user_query}
{type_hint}
{original_data_section}
{schema_hint}
# Execution Result (after processing):
{df_str}
{all_paths_section}

# Question Analysis
{question_analysis}

{special_guidance}

CRITICAL INSTRUCTIONS:
1. **Read the question CAREFULLY** - Identify what is being asked:
   - Maximum/minimum value? → Extract max/min
   - Specific year/date? → Extract that value
   - Count? → Extract count number
   - Multiple values? → Extract all requested
   - Yes/No? → Answer 'Yes' or 'No'
   - Visualization? → Output Python code (NOT description!)

2. **Examine the Execution Result carefully**:
   - 1 row: Extract value(s) from that row
   - Multiple rows: 
     * Max/min: Find row with max/min value
     * List: Extract all relevant values
     * Count: Count rows or extract count
   - Empty: Check Original Table Data

3. **Check Original Table Data**:
   - Special rows: "Total", "Sum", "Average"
   - Hierarchical groupings (age groups, etc.)
   - Understand structure before extracting

4. **Verify your answer**:
   - Does it directly answer the question?
   - Correct column(s)?
   - Right row(s)?
   - Calculations accurate?

5. **Question Type Handling** (CRITICAL):
   
   ⭐ **FOR DATA ANALYSIS QUESTIONS ONLY**:
   - Provide comprehensive, detailed analysis report (300-700 words)
   - Include: Data overview, calculation steps, statistical details, insights, context
   
   ❌ **FOR ALL OTHER TYPES** (Fact Checking, Numerical Reasoning, Ranking, etc.):
   - Extract ONLY the specific answer value
   - NO explanations, NO analysis, NO reasoning steps
   
   📊 **FOR VISUALIZATION QUESTIONS**:
   - Output ONLY executable Python code (NOT descriptions)

6. **Use Original Table Data for context** - understand meanings and structure

7. **Output ONE answer only** - extract specific information requested

8. **Handle edge cases**:
   - Empty/NaN → "[Final Answer]: No data available"
   - One row → extract value(s)
   - Multiple rows → follow question intent

9. **Format: "[Final Answer]: <answer>"**

10. **For Visualization**: Output code in markdown code block

11. **For multiple values**: comma-space separator (e.g., "1955, 62170")

12. **For single values**: just the value (e.g., "42")

13. **For decimals**: keep 2 decimal places (e.g., 0.44)

14. **For Yes/No**: answer ONLY 'Yes' or 'No'

15. **Remove thousand separators** (99,826 -> 99826)

16. **NEVER include NaN/null** unless truly no data

Examples:
- Q: "What year had max agriculture?" Result: Year=1955 → "[Final Answer]: 1955"
- Q: "Year and population when agriculture was highest?" Result: Year=1955, Pop=62170 → "[Final Answer]: 1955, 62170"
- Q: "Create a bar chart" (Visualization) → "[Final Answer]: ```python\nimport matplotlib.pyplot as plt\n...\nplt.show()```"

Now answer based on the result(s) above. Output ONLY the answer line:
"""
        return prompt
    
    def _format_dataframe(self, df: pd.DataFrame, max_rows: int = 10, use_markdown: bool = True) -> str:
        """
        格式化DataFrame为文本/Markdown，使其更容易理解
        
        Args:
            df: DataFrame to format
            max_rows: Maximum rows to display
            use_markdown: If True, use Markdown table format (better for LLM understanding)
        """
        
        if df.empty:
            return "Empty DataFrame (no rows)"
        
        # 限制显示行数
        display_df = df.head(max_rows) if len(df) > max_rows else df
        
        lines = []
        lines.append(f"Shape: {df.shape[0]} rows × {df.shape[1]} columns")
        lines.append(f"Columns: {list(df.columns)}")
        
        # 添加数据类型信息
        if len(df.columns) <= 10:  # 只在列数不多时显示类型
            dtype_info = {col: str(dtype) for col, dtype in df.dtypes.items()}
            lines.append(f"Data Types: {dtype_info}")
        
        lines.append("")
        lines.append("Data:")
        
        # ⭐ 使用Markdown格式（更结构化，LLM更容易解析）
        if use_markdown:
            try:
                # 手动生成Markdown表格（兼容旧版pandas）
                markdown_table = self._dataframe_to_markdown(display_df)
                lines.append(markdown_table)
            except Exception as e:
                # Fallback to to_string if markdown generation fails
                self.logger.warning(f"Failed to generate markdown table: {e}, falling back to to_string")
                lines.append(display_df.to_string(index=False))
        else:
            lines.append(display_df.to_string(index=False))
        
        # 如果只有少量行，添加统计信息
        if len(df) <= 5:
            lines.append("\nSummary:")
            for col in df.columns:
                if pd.api.types.is_numeric_dtype(df[col]):
                    lines.append(f"  {col}: min={df[col].min()}, max={df[col].max()}, mean={df[col].mean():.2f}")
        
        if len(df) > max_rows:
            lines.append(f"\n(Showing first {max_rows} of {len(df)} rows)")
        
        return "\n".join(lines)
    
    def _dataframe_to_markdown(self, df: pd.DataFrame) -> str:
        """
        手动将DataFrame转换为Markdown表格格式
        兼容旧版pandas（0.23.x）
        
        Example output:
        | Year | Population | Agriculture |
        |------|------------|-------------|
        | 1953 | 61179      | 15888       |
        | 1955 | 62170      | 16234       |
        """
        if df.empty:
            return "Empty DataFrame"
        
        lines = []
        
        # Header row
        headers = list(df.columns)
        header_line = "| " + " | ".join(str(h) for h in headers) + " |"
        lines.append(header_line)
        
        # Separator row
        separator_line = "|" + "|".join("-" * (len(str(h)) + 2) for h in headers) + "|"
        lines.append(separator_line)
        
        # Data rows
        for idx in range(len(df)):
            row_values = []
            for col in df.columns:
                val = df.iloc[idx][col]
                # Format value
                if pd.isna(val):
                    row_values.append("NaN")
                elif isinstance(val, (int, float)):
                    # Format numbers nicely
                    if isinstance(val, float) and val == int(val):
                        row_values.append(str(int(val)))
                    else:
                        row_values.append(str(val))
                else:
                    row_values.append(str(val))
            
            data_line = "| " + " | ".join(row_values) + " |"
            lines.append(data_line)
        
        return "\n".join(lines)
    
    def _format_answer(self, raw_answer: str, is_short_answer: bool = False) -> str:
        """清理LLM输出
        
        Args:
            raw_answer: LLM原始输出
            is_short_answer: 是否为短答案类型（用于更激进的清理）
        """
        
        answer = raw_answer.strip()
        
        # 🔧 CRITICAL FIX: Clean f-string placeholders from the answer
        # Pattern: {variable_name:.2f} or {object.attr[0]:.1%} etc.
        import re
        fstring_pattern = r'\{[a-zA-Z_][\w]*(?:\.[a-zA-Z_][\w]*)*(?:\[[^\]]+\])*(?::[^}]+)?\}'
        
        # Check if answer contains f-string placeholders
        if re.search(fstring_pattern, answer):
            self.logger.warning("⚠️  Found f-string placeholders in answer, cleaning...")
            # Replace with placeholder text
            answer = re.sub(fstring_pattern, '[value]', answer)
            self.logger.warning(f"✓ Cleaned f-string placeholders")
        
        # 提取 [Final Answer]: 后的内容
        match = re.search(r'\[Final Answer\]:\s*(.+)', answer, re.IGNORECASE | re.DOTALL)
        if match:
            content = match.group(1).strip()
            # 移除可能的尾部句号或换行
            content = content.rstrip('.\n')
            
            # ⭐⭐ 短答案类型：激进清理策略
            if is_short_answer:
                # 1. 如果第一行看起来是答案（短且没有"To"/"Follow"等），只取第一行
                first_line = content.split('\n')[0].strip()
                if first_line:
                    # 检查第一行是否为纯值（没有解释性文字）
                    if len(first_line) < 150 and not any(word in first_line.lower() for word in ['to find', 'follow', 'from the', 'first', 'next', 'then', 'finally']):
                        content = first_line
                        self.logger.info(f"✂️  Extracted first line as short answer: {content[:50]}...")
                    elif len(content) > 200:
                        # 如果超过200字符但第一行有解释性文字，尝试找到纯值
                        # 尝试匹配常见的短答案模式
                        patterns = [
                            r'^([Yy]es|[Nn]o)\s*$',  # Yes/No
                            r'^(\d+(?:,\d+)*(?:\.\d+)?(?:\s*,\s*\d+(?:,\d+)*(?:\.\d+)?)*)\s*$',  # 数字
                            r'^([A-Za-z0-9\s,]+(?:\s+years?)?)\s*$',  # 年份、年龄组等
                        ]
                        for pattern in patterns:
                            value_match = re.match(pattern, first_line)
                            if value_match:
                                content = value_match.group(1).strip()
                                self.logger.info(f"✂️  Extracted value pattern: {content}")
                                break
                        else:
                            # 没有匹配到模式，取第一行
                            content = first_line
            elif len(content) > 200:
                # 非短答案类型：如果答案超过200字符，提取第一行（保留原逻辑）
                first_line = content.split('\n')[0].strip()
                if first_line and len(first_line) < 200:
                    self.logger.info(f"✂️  Truncated long answer ({len(content)} chars) to first line ({len(first_line)} chars)")
                    content = first_line
            
            # ⭐⭐ 数值格式化：移除不必要的 .0 后缀
            # 例如: "158772.0" → "158772", "1955, 62170.0" → "1955, 62170"
            content = self._clean_number_format(content)
            
            return f"[Final Answer]: {content}"
        
        # 如果没有标记，添加
        return f"[Final Answer]: {answer}"
    
    def _generate_fallback(self, df: pd.DataFrame) -> str:
        """Fallback答案（LLM失败时）"""
        import re
        
        if df.empty:
            return "No data"
        
        # 🔧 FIX: Clean f-string placeholders from DataFrame
        fstring_pattern = r'\{[a-zA-Z_][\w]*(?:\.[a-zA-Z_][\w]*)*(?:\[[^\]]+\])*(?::[^}]+)?\}'
        
        # 如果只有1行，拼接所有非NaN值
        if len(df) == 1:
            values = []
            for col in df.columns:
                val = df.iloc[0][col]
                if pd.notna(val):
                    val_str = str(val)
                    
                    # Skip f-string placeholders
                    if re.match(fstring_pattern, val_str):
                        self.logger.warning(f"Skipping f-string placeholder in fallback: {val_str}")
                        continue
                    
                    # 格式化数字
                    if isinstance(val, (int, float)):
                        if val == int(val):
                            values.append(str(int(val)))
                        else:
                            values.append(str(val))
                    else:
                        values.append(val_str)
            
            return ", ".join(values) if values else "No valid data"
        
        # 多行：检查是否所有值都是f-string placeholders
        contains_placeholders = False
        for col in df.columns:
            for val in df[col]:
                if pd.notna(val) and re.match(fstring_pattern, str(val)):
                    contains_placeholders = True
                    break
            if contains_placeholders:
                break
        
        if contains_placeholders:
            return f"{len(df)} rows (contains format placeholders - execution may have failed)"
        
        # 多行：返回简单描述
        return f"{len(df)} rows found"
    
    def _analyze_question_intent(self, user_query: str) -> str:
        """分析问题意图，帮助LLM更好地理解问题"""
        query_lower = user_query.lower()
        
        intent_parts = []
        
        # 检测问题类型
        if any(word in query_lower for word in ['max', 'maximum', 'highest', 'largest', 'greatest', 'top']):
            intent_parts.append("- **Intent**: Finding MAXIMUM value")
            intent_parts.append("- **Action**: Look for the row with the highest value in the relevant column")
        elif any(word in query_lower for word in ['min', 'minimum', 'lowest', 'smallest', 'bottom']):
            intent_parts.append("- **Intent**: Finding MINIMUM value")
            intent_parts.append("- **Action**: Look for the row with the lowest value in the relevant column")
        elif any(word in query_lower for word in ['count', 'number of', 'how many']):
            intent_parts.append("- **Intent**: Counting items")
            intent_parts.append("- **Action**: Count rows or extract count value")
        elif any(word in query_lower for word in ['yes', 'no', 'is', 'are', 'does', 'do', 'can', 'will']):
            if '?' in user_query:
                intent_parts.append("- **Intent**: Yes/No question")
                intent_parts.append("- **Action**: Analyze data and answer 'Yes' or 'No'")
        elif any(word in query_lower for word in ['list', 'all', 'every', 'each']):
            intent_parts.append("- **Intent**: Listing multiple values")
            intent_parts.append("- **Action**: Extract all relevant values")
        elif any(word in query_lower for word in ['when', 'year', 'date', 'time']):
            intent_parts.append("- **Intent**: Finding specific time/date")
            intent_parts.append("- **Action**: Extract the year/date value")
        elif any(word in query_lower for word in ['what', 'which', 'who', 'where']):
            intent_parts.append("- **Intent**: Finding specific entity/value")
            intent_parts.append("- **Action**: Extract the specific value(s) requested")
        
        if not intent_parts:
            intent_parts.append("- **Intent**: General query")
            intent_parts.append("- **Action**: Extract the relevant information from the result")
        
        return "\n".join(intent_parts)
    
    def _generate_direct_llm_answer(
        self, 
        user_query: str, 
        original_df: pd.DataFrame, 
        question_type: str,
        sub_q_type: str = "",
        enable_multi_round: bool = True
    ) -> str:
        """
        直接使用LLM回答，不依赖代码执行结果（作为错误兜底）
        类似于baseline方法，直接让LLM看表格数据回答
        
        V8.1增强: 支持multi-round reasoning和reflection
        RealtHitBench增强: 短答案类型使用简洁Prompt
        """
        try:
            # ⭐ 判断是否为短答案类型
            is_short_answer = self._is_short_answer_type(question_type, sub_q_type)
            
            # 获取prompt模板
            prompt_template = None
            answer_format = "AnswerName1, AnswerName2..."
            
            if PROMPT_TEMPLATES_AVAILABLE and question_type:
                if question_type == "Data Analysis" and sub_q_type:
                    prompt_template = Answer_Prompt.get(sub_q_type)
                    if not prompt_template:
                        prompt_template = Answer_Prompt.get("Rudimentary Analysis", Answer_Prompt.get("Fact Checking"))
                elif question_type in Answer_Prompt:
                    prompt_template = Answer_Prompt.get(question_type)
                
                if sub_q_type == "Exploratory Analysis":
                    answer_format = "CorrelationRelation, CorrelationCoefficient"
                elif question_type == "Visualization":
                    answer_format = "Python code"
                elif question_type == "Summary Analysis":
                    answer_format = "TableSummary"
                elif question_type == "Anomaly Analysis":
                    answer_format = "Conclusion"
            
            # 格式化表格数据（显示更多行，让LLM有足够信息）
            table_str = self._format_dataframe(original_df, max_rows=200)
            
            # ==================== Round 1: Initial Generation ====================
            self.logger.info(f"🔄 Fallback LLM: Round 1 - Initial answer generation... (Short Answer Mode: {is_short_answer})")
            
            # 构建prompt（区分短答案和长答案）
            if is_short_answer:
                # ⭐ 短答案：简洁Prompt
                if prompt_template:
                    prompt = f"""{prompt_template}

# Table
{table_str}

# Question
{user_query}

⭐⭐⭐ CONCISE ANSWER MODE - NO EXPLANATIONS ⭐⭐⭐
**This question requires a SHORT answer. You MUST output ONLY the value.**

**CRITICAL - DO NOT include any of these:**
- ❌ "To find..." or "Follow these steps..."
- ❌ "From the table..."
- ❌ Any reasoning or explanation

**ONLY OUTPUT:**
```
[Final Answer]: <value>
```

**Instructions:**
1. Extract the EXACT answer from the table
2. Single value → Output value only (e.g., "1955")
3. Multiple values → Comma-separated (e.g., "1955, 62170")
4. Yes/No → "Yes" or "No" only
5. Remove commas from numbers: 99,826 → 99826
6. **NEVER** use {{placeholders}}

**Example - CORRECT:**
[Final Answer]: 1955

**Example - WRONG:**
To find the year, look at row 5. [Final Answer]: 1955

**NOW OUTPUT ONLY THE ANSWER LINE:**
"""
                else:
                    prompt = f"""Answer this question based on table data.

# Table
{table_str}

# Question
{user_query}

⭐⭐⭐ CONCISE ANSWER MODE - Critical ⭐⭐⭐
**This is a SHORT ANSWER question. Output ONLY the value, NO explanations.**

**STRICT RULES - DO NOT:**
- Include "To find..." or step-by-step reasoning
- Add "From the table..." or explanations
- Use {{placeholders}}

**ONLY OUTPUT:**
[Final Answer]: <value>

**Format rules:**
- Single value → e.g., "1955"
- Multiple values → e.g., "1955, 62170"  
- Yes/No → "Yes" or "No" only
- Remove commas from numbers

**Example: If asking for year 1955, ONLY output:**
[Final Answer]: 1955

**Now output your answer:**
"""
            else:
                # 长答案：完整Prompt（保持原有逻辑）
                if prompt_template:
                    prompt = f"""{prompt_template}

# Table
{table_str}

# Question
{user_query}

Emphasize: you need to make sure your final answer is formatted in this way: [Final Answer]: {answer_format}

# Critical Instructions:
1. Read the table carefully and understand its structure
2. Pay attention to special indicators such as 'Total', 'Sum', 'Average', 'Mean', etc. in row/column headers
3. Identify the relevant rows and columns based on the question
4. Extract the exact answer from the table
5. For numerical answers, keep 2 decimal places for floats
6. Remove thousand separators from numbers
7. For Yes/No questions, answer ONLY 'Yes' or 'No'
8. Use the original format from the table when possible
9. **NEVER** use format placeholders like {{{{var:.2f}}}} - use actual numbers

Now provide your answer:
"""
                else:
                    # 使用通用prompt
                    prompt = f"""You are answering a question based on table data.

# Table
{table_str}

# Question
{user_query}

# Question Type: {question_type}

# Instructions:
1. Read the table carefully
2. Pay attention to special indicators such as 'Total', 'Sum', 'Average', 'Mean', etc.
3. Identify relevant rows and columns
4. Extract the exact answer
5. Format: "[Final Answer]: <answer>"
6. For numerical answers, keep 2 decimal places for floats
7. Remove thousand separators from numbers
8. For Yes/No questions, answer ONLY 'Yes' or 'No'
9. **NEVER** use format placeholders like {{{{var:.2f}}}} - use actual numbers

Now provide your answer:
"""
            
            raw_answer = self.llm_client.call_api(prompt)
            first_formatted = self._format_answer(raw_answer, is_short_answer=is_short_answer)
            
            # 如果不启用multi-round，直接返回
            if not enable_multi_round:
                return first_formatted
            
            # ==================== Round 2: Deep Reflection & Refinement ====================
            self.logger.info("🔄 Fallback LLM: Round 2 - Deep reflection and refinement...")
            
            # 检测第一轮答案的问题
            issues = []
            if self._has_format_errors(first_formatted):
                issues.append("❌ Contains format placeholders like {{var:.2f}}")
            if len(first_formatted) < 50:
                issues.append("⚠️  Answer is too brief (< 50 chars)")
            if "unable to generate" in first_formatted.lower() or "technical error" in first_formatted.lower():
                issues.append("⚠️  Contains error messages")
            
            issues_text = "\n".join(f"  {issue}" for issue in issues) if issues else "  ✅ No major issues detected"
            
            critique_prompt = f"""# 🔍 CRITICAL SELF-REVIEW (Fallback Mode - Code Execution Failed)

You previously generated this answer when the system couldn't execute code:

## Your First Draft
{first_formatted}

---

## Original Question
{user_query}

---

## Automatic Quality Check
{issues_text}

---

## 📊 Available Data (for verification)
{table_str}

---

## 📋 Deep Reflection Checklist

**1. Format & Structure (CRITICAL!)**
- [ ] Are there any {{{{placeholder}}}} or {{{{var:.2f}}}} format strings? **MUST REMOVE!**
- [ ] Is the answer in proper Markdown format (##, |, **, *)?
- [ ] Does it start with "[Final Answer]:" if required?

**2. Accuracy & Data Extraction**
- [ ] Did I extract **exact** numbers from the table?
- [ ] Did I verify values against the data above?
- [ ] Are column names and row values correct?

**3. Completeness**
- [ ] Did I answer **ALL parts** of the question?
- [ ] Are there any error messages or "unable to" statements?
- [ ] Is the answer complete and not truncated?

**4. Analysis Quality (for Data Analysis questions)**
- [ ] Did I explain **WHY**, not just WHAT?
- [ ] Did I identify patterns or trends?
- [ ] Did I provide context or implications?

**5. Common Errors to Fix**
- ❌ {{{{var:.2f}}}} placeholders → Replace with actual numbers
- ❌ "Unable to generate" → Provide actual analysis
- ❌ Generic statements → Add specific data points
- ❌ Missing data → Extract from table above

---

## 🎯 Your Task

Generate an **IMPROVED VERSION** that:
1. **Removes ALL format placeholders** ({{{{...}}}}) - this is NON-NEGOTIABLE!
2. **Extracts exact data** from the table above
3. **Provides complete analysis** (no error messages)
4. **Uses proper format** (Markdown for analysis, "[Final Answer]: value" for simple questions)

**If the first answer is already good** (no placeholders, complete, accurate), output it with minor improvements.

---

Output your **REFINED ANSWER** now:
"""
            
            refined_answer = self.llm_client.call_api(critique_prompt)
            refined_formatted = self._format_answer(refined_answer, is_short_answer=is_short_answer)
            
            self.logger.info("✅ Fallback LLM: Multi-round completed (2 rounds)")
            return refined_formatted
            
        except Exception as e:
            self.logger.error(f"Failed to generate direct LLM answer: {e}")
            return "[Final Answer]: No data available"
    
    def _has_format_errors(self, answer: str) -> bool:
        """检测答案是否包含格式错误（如format placeholders）"""
        import re
        # 检测 {xxx:xxx} 格式的占位符
        if re.search(r'\{[^}]*:[^}]*\}', answer):
            return True
        # 检测 {xxx()} 格式的函数调用占位符
        if re.search(r'\{\w+\([^)]*\)[^}]*\}', answer):
            return True
        return False
    
    def _try_extract_from_original(self, user_query: str, original_df: pd.DataFrame, question_type: str) -> Optional[str]:
        """
        尝试从原始数据中提取答案（当执行结果为空时）
        
        Args:
            user_query: 用户问题
            original_df: 原始数据DataFrame
            question_type: 问题类型
            
        Returns:
            提取的答案，如果无法提取则返回None
        """
        try:
            # 构建一个简单的prompt，让LLM从原始数据中提取答案
            prompt = f"""You need to answer a question based on the original table data.

Question: {user_query}
Question Type: {question_type}

# Original Table Data:
{self._format_dataframe(original_df, max_rows=50)}

IMPORTANT: Even if the data seems incomplete, try to extract the best possible answer from the available data.
- Look for keywords in the question that match column names or row values
- For numerical questions, try to find the relevant numbers
- For yes/no questions, analyze the data and answer 'Yes' or 'No'
- Only return "[Final Answer]: No data available" if absolutely no relevant information exists

Output format: [Final Answer]: <your answer>
"""
            
            raw_answer = self.llm_client.call_api(prompt)
            formatted = self._format_answer(raw_answer)
            
            # 检查是否真的没有数据
            if "no data available" in formatted.lower() or "no data" in formatted.lower():
                return None
            
            return formatted
            
        except Exception as e:
            self.logger.warning(f"Failed to extract from original data: {e}")
            return None
    
    def _clean_number_format(self, text: str) -> str:
        """
        清理数字格式：移除不必要的.0后缀
        例如: "158772.0" → "158772", "1955, 62170.0" → "1955, 62170"
        但保留真正的小数: "5.80" → "5.80"
        """
        import re
        
        # 匹配数字.0的模式（但不是0.x这种真正的小数）
        # 策略：替换所有 数字.0 为 数字（只要不是 0.x 这种小于1的小数）
        def replace_fn(match):
            full_num = match.group(0)
            # 检查是否以 .0 结尾且前面的数字大于等于1
            if '.' in full_num:
                parts = full_num.split('.')
                if len(parts) == 2 and parts[1] == '0':
                    # 如果整数部分是0，保留（如0.0）
                    # 否则移除.0
                    try:
                        int_part = int(parts[0])
                        if int_part >= 1:
                            return parts[0]
                    except:
                        pass
            return full_num
        
        # 匹配所有数字（包括小数）
        cleaned = re.sub(r'\d+\.?\d*', replace_fn, text)
        return cleaned
    
    def _is_short_answer_type(self, question_type: str, sub_q_type: str = "") -> bool:
        """
        判断是否为短答案类型（需要简洁输出）
        
        短答案类型包括:
        - Fact Checking (78.6% of RealtHitBench)
        - Numerical Reasoning
        - Structure Comprehending
        
        长答案类型包括:
        - Data Analysis (except Rudimentary Analysis)
        - Visualization
        
        Returns:
            True if short answer type, False otherwise
        """
        # 明确的长答案类型
        if question_type == "Visualization":
            return False
        
        if question_type == "Data Analysis":
            # Data Analysis中，只有Rudimentary Analysis是短答案
            if sub_q_type == "Rudimentary Analysis":
                return True
            # Summary/Exploratory/Predictive/Anomaly Analysis 需要长答案
            return False
        
        # 所有其他类型默认为短答案
        # Fact Checking, Numerical Reasoning, Structure Comprehending
        return True

