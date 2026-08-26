"""
MODULE 3 - SMG (Structured Memory Graph)

PURPOSE:
- THE ONLY module that generates executable code
- THE ONLY module that executes code
- Evaluates execution outcomes via LLM reward evaluator
- Updates structured memory
- Manages path execution with failure handling

EXECUTION PROCESS:
For each selected path (A then B):
    for operator in path:
        generate code for operator
        execute code
        evaluate execution result via LLM
        receive structured reward
        update SMG memory
        if failure:
            stop this path
"""

import time
import re
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
from src.core.dtr_structures import (
    Operator, ExecutionPath, TableState, SMGNode, RewardVector
)


class SMGModule:
    """
    Structured Memory Graph Module.
    Handles code generation, execution, and memory management.
    """
    
    def __init__(self, llm_client, reward_evaluator, enable_multi_stage=False):
        """
        Args:
            llm_client: LLM client for code generation
            reward_evaluator: RewardEvaluator instance
            enable_multi_stage: Enable multi-stage code generation (Understanding-Generation-Reflection)
        """
        self.llm_client = llm_client
        self.reward_evaluator = reward_evaluator
        self.enable_multi_stage = enable_multi_stage
        
        # Memory storage
        self.memory: List[SMGNode] = []
        
        # Persistent memory across runs (simple in-memory for now)
        self.persistent_memory: Dict[str, List[SMGNode]] = {}
    
    def execute_paths(
        self,
        paths: List[ExecutionPath],
        operator_pool: List[Operator],
        dataframe,
        user_query: str,
        table_metadata: Dict[str, Any],
        schema_result=None
    ) -> Dict[str, Any]:
        """
        Execute multiple paths and return results.
        
        Args:
            paths: List of ExecutionPath objects (usually top 2)
            operator_pool: All available operators
            dataframe: Initial pandas DataFrame
            user_query: Original user query
            table_metadata: Table metadata dict
            schema_result: Optional SchemaLinkingResult with selected headers
        
        Returns:
            Dict with keys: best_path, best_df, all_results, memory_nodes
        """
        operator_map = {op.name: op for op in operator_pool}
        
        print(f"\n{'='*70}")
        print(f"🚀 PARALLEL EXECUTION: {len(paths)} paths")
        print(f"{'='*70}")
        
        # Phase 1: 并行执行所有paths（不评估reward）
        all_path_results = []
        all_operations_for_eval = []  # 收集所有需要评估的operations
        
        for path_idx, path in enumerate(paths):
            print(f"\n[Path {path_idx+1}/{len(paths)}] {path.path_id}: {' → '.join(path.operators)}")
            
            # 执行path（不评估reward）
            result = self._execute_single_path_no_eval(
                path=path,
                operator_map=operator_map,
                dataframe=dataframe,
                user_query=user_query,
                table_metadata=table_metadata,
                schema_result=schema_result
            )
            
            all_path_results.append(result)
            
            # 收集operations用于批量评估
            all_operations_for_eval.extend(result['operations_for_eval'])
            
            # 显示执行结果
            success_count = sum(1 for op in result['operations_for_eval'] if op['success'])
            print(f"  ✓ Executed: {success_count}/{len(result['operations_for_eval'])} succeeded")
        
        # Phase 2: 批量评估所有operations的reward
        print(f"\n{'='*70}")
        print(f"📊 BATCH REWARD EVALUATION: {len(all_operations_for_eval)} operations")
        print(f"{'='*70}")
        
        start_eval = time.time()
        all_rewards = self.reward_evaluator.evaluate_batch(all_operations_for_eval)
        eval_time = time.time() - start_eval
        
        print(f"✓ Batch evaluation completed in {eval_time:.2f}s ({len(all_operations_for_eval)/eval_time:.1f} ops/s)")
        
        # Phase 3: 分配rewards到各个path的operations
        reward_idx = 0
        for path_result in all_path_results:
            path_ops = path_result['operations_for_eval']
            path_rewards = all_rewards[reward_idx:reward_idx + len(path_ops)]
            reward_idx += len(path_ops)
            
            # 更新path结果
            self._finalize_path_with_rewards(path_result, path_rewards)
        
        # Phase 4: 选择最佳path
        best_result = max(all_path_results, key=lambda x: x['cumulative_reward'])
        
        print(f"\n{'='*70}")
        print(f"🏆 BEST PATH: {best_result['path_id']}")
        print(f"   Reward: {best_result['cumulative_reward']:.3f}")
        print(f"   Success Rate: {best_result['success_count']}/{best_result['total_ops']}")
        print(f"{'='*70}")
        
        return {
            "best_path": best_result["path_id"],
            "best_df": best_result["final_df"],
            "best_reward": best_result["cumulative_reward"],
            "all_results": all_path_results,
            "memory_nodes": self.memory
        }
    
    def _execute_single_path_no_eval(
        self,
        path: ExecutionPath,
        operator_map: Dict[str, Operator],
        dataframe,
        user_query: str,
        table_metadata: Dict[str, Any],
        schema_result=None
    ) -> Dict[str, Any]:
        """
        执行单个path但不评估reward（用于批量评估）
        
        Args:
            schema_result: Optional SchemaLinkingResult for code generation guidance
        
        Returns:
            Dict with:
                - path_id
                - final_df
                - operations_for_eval: List of dicts for batch evaluation
                - smg_nodes: List of SMGNode objects (reward未填充)
        """
        
        import pandas as pd
        
        current_df = dataframe.copy() if dataframe is not None else pd.DataFrame()
        operations_for_eval = []
        smg_nodes = []
        
        for step_idx, op_name in enumerate(path.operators):
            operator = operator_map.get(op_name)
            
            if not operator:
                print(f"  [Step {step_idx+1}] ⚠️  Unknown operator: {op_name}, skipping")
                continue
            
            # Capture state before
            state_before = TableState()
            state_before.update_from_dataframe(current_df)
            before_df = current_df.copy()
            
            # Build step context
            step_context = self._build_step_context(
                current_step=step_idx,
                operators=path.operators,
                current_operator=operator.name,
                user_query=user_query
            )
            
            # ⭐ Multi-Stage Code Generation (MVP: only for first operator)
            use_multi_stage = self.enable_multi_stage and step_idx == 0
            reflection_result = None
            
            if use_multi_stage:
                print(f"  [Step {step_idx+1}] 🎯 Using Multi-Stage Code Generation")
                code, code_gen_prompt, reflection_result = self._generate_code_with_stages(
                    operator=operator,
                    dataframe=current_df,
                    user_query=user_query,
                    table_metadata=table_metadata,
                    step_context=step_context,
                    schema_result=schema_result
                )
            else:
                # Generate code (traditional single-stage)
                code, code_gen_prompt = self._generate_code(
                    operator=operator,
                    dataframe=current_df,
                    user_query=user_query,
                    table_metadata=table_metadata,
                    step_context=step_context,
                    schema_result=schema_result
                )
            
            # Execute code
            start_time = time.time()
            exec_result = self._execute_code(code, current_df)
            execution_time = time.time() - start_time
            
            success = exec_result["success"]
            error_msg = exec_result.get("error", "")
            
            # Capture state after
            state_after = TableState()
            after_df = None
            if success:
                result_df = exec_result["dataframe"]
                current_df = result_df
                after_df = current_df.copy()
                state_after.update_from_dataframe(current_df)
            
            # 收集operation信息用于批量评估
            operations_for_eval.append({
                'code': code,
                'operator_name': operator.name,
                'user_query': operator.description,
                'original_query': user_query,
                'success': success,
                'error': error_msg,
                'before_df': before_df,
                'after_df': after_df,
                'execution_time': execution_time
            })
            
            # 创建SMGNode（reward稍后填充）
            smg_node = SMGNode(
                operator_name=operator.name,
                code=code,
                state_before=state_before,
                state_after=state_after if success else None,
                success=success,
                error_message=error_msg,
                execution_time=execution_time,
                reward_vector=None  # 稍后填充
            )
            smg_nodes.append(smg_node)
        
        return {
            'path_id': path.path_id,
            'final_df': current_df,
            'operations_for_eval': operations_for_eval,
            'smg_nodes': smg_nodes,
            'cumulative_reward': 0.0,  # 稍后计算
            'success_count': 0,  # 稍后计算
            'total_ops': len(smg_nodes)
        }
    
    def _finalize_path_with_rewards(
        self,
        path_result: Dict[str, Any],
        rewards: List[RewardVector]
    ):
        """用批量评估的rewards更新path结果"""
        
        smg_nodes = path_result['smg_nodes']
        cumulative_reward = 0.0
        success_count = 0
        
        for node, reward in zip(smg_nodes, rewards):
            # 填充reward
            node.reward_vector = reward
            
            # 聚合reward
            aggregated = self._aggregate_sub_rewards(reward)
            cumulative_reward += aggregated
            
            if node.success:
                success_count += 1
            
            # 添加到memory
            self.memory.append(node)
        
        # 更新path结果
        path_result['cumulative_reward'] = cumulative_reward
        path_result['success_count'] = success_count
    
    def _execute_single_path(
        self,
        path: ExecutionPath,
        operator_map: Dict[str, Operator],
        dataframe,
        user_query: str,
        table_metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a single path operator by operator (旧版本，保留兼容性)"""
        
        import pandas as pd
        
        current_df = dataframe.copy() if dataframe is not None else pd.DataFrame()
        path_memory_nodes = []
        cumulative_reward = 0.0
        execution_stopped = False
        stop_reason = ""
        
        for step_idx, op_name in enumerate(path.operators):
            operator = operator_map.get(op_name)
            
            if not operator:
                print(f"  [Step {step_idx+1}] ⚠️  Unknown operator: {op_name}, skipping")
                continue
            
            print(f"  [Step {step_idx+1}] Executing: {operator.name}")
            
            # Capture state before
            state_before = TableState()
            state_before.update_from_dataframe(current_df)
            
            # Build rich step context with full execution plan
            step_context = self._build_step_context(
                current_step=step_idx,
                operators=path.operators,
                current_operator=operator.name,
                user_query=user_query
            )
            
            # Generate code
            code, code_gen_prompt = self._generate_code(
                operator=operator,
                dataframe=current_df,
                user_query=user_query,
                table_metadata=table_metadata,
                step_context=step_context,
                schema_result=schema_result
            )
            
            # Execute code
            start_time = time.time()
            exec_result = self._execute_code(code, current_df)
            execution_time = time.time() - start_time
            
            success = exec_result["success"]
            error_msg = exec_result.get("error", "")
            
            # Capture state after
            state_after = TableState()
            if success:
                result_df = exec_result["dataframe"]
                current_df = result_df
                state_after.update_from_dataframe(current_df)
                print(f"    ✓ Success (shape: {current_df.shape}, time: {execution_time:.2f}s)")
            else:
                print(f"    ✗ Failed: {error_msg[:100]}")
            
            # Evaluate via LLM
            reward = self.reward_evaluator.evaluate(
                operator_name=operator.name,
                code=code,
                execution_success=success,
                error_message=error_msg,
                state_before=state_before,
                state_after=state_after if success else None,
                user_query=operator.description,
                original_query=user_query
            )
            
            # Aggregate reward using system-level function (LLM does NOT participate in weighting)
            aggregated_reward = self._aggregate_sub_rewards(reward)
            
            print(f"    Sub-rewards: exec={reward.execution_success:.1f}, query={reward.query_satisfaction:.1f}, reason={reward.code_reasonableness:.1f}, eff={reward.efficiency:.1f}, err_sev={reward.error_severity:.1f}")
            print(f"    Aggregated Reward: {aggregated_reward:.3f}")
            
            # Create SMG node
            smg_node = SMGNode(
                operator_name=operator.name,
                code=code,
                success=success,
                error_message=error_msg,
                state_before=state_before,
                state_after=state_after if success else None,
                reward_vector=reward,
                execution_time=execution_time,
                timestamp=datetime.now().isoformat()
            )
            
            path_memory_nodes.append(smg_node)
            self.memory.append(smg_node)
            
            # Use aggregated reward (not LLM's total_score)
            cumulative_reward += aggregated_reward
            
            # Update context signature for SMG learning
            self._update_smg_context(
                operator=operator,
                context=self._get_table_signature(current_df),
                reward_vector=reward,
                success=success
            )
            
            # Check for critical failure
            if not success and reward.error_severity > 0.5:
                execution_stopped = True
                stop_reason = f"Critical failure at {operator.name}"
                print(f"    ⚠️  Stopping path due to critical failure")
                break
        
        return {
            "path_id": path.path_id,
            "operators": path.operators,
            "memory_nodes": path_memory_nodes,
            "final_df": current_df,
            "cumulative_reward": cumulative_reward,
            "execution_stopped": execution_stopped,
            "stop_reason": stop_reason
        }
    
    def _build_step_context(
        self,
        current_step: int,
        operators: List[str],
        current_operator: str,
        user_query: str
    ) -> str:
        """
        Build rich context showing the full execution plan and current position.
        This helps LLM understand WHY this step is needed and HOW it fits in the overall goal.
        """
        total_steps = len(operators)
        
        # Build execution plan visualization
        plan_lines = []
        plan_lines.append(f"## Execution Plan ({total_steps} steps total)")
        plan_lines.append(f"Goal: {user_query}")
        plan_lines.append("\nPlan:")
        
        for idx, op_name in enumerate(operators):
            if idx == current_step:
                plan_lines.append(f"  {idx+1}. **{op_name}** ← YOU ARE HERE")
            elif idx < current_step:
                plan_lines.append(f"  {idx+1}. {op_name} ✓ (completed)")
            else:
                plan_lines.append(f"  {idx+1}. {op_name} (upcoming)")
        
        plan_lines.append(f"\n⭐ Your task: Execute step {current_step+1} ({current_operator})")
        plan_lines.append(f"⭐ Remember: This step should help achieve the overall goal: '{user_query}'")
        
        return "\n".join(plan_lines)
    
    def _generate_code(
        self,
        operator: Operator,
        dataframe,
        user_query: str,
        table_metadata: Dict[str, Any],
        step_context: str = "",
        schema_result=None
    ) -> Tuple[str, str]:
        """
        Generate code for an operator using LLM.
        
        ⭐ KEY IMPROVEMENT: 利用历史经验生成更robust的代码
        ⭐ SCHEMA ENHANCEMENT: 利用Schema信息指导列选择
        
        Args:
            schema_result: Optional SchemaLinkingResult with relevant headers
        
        Returns (code, prompt)
        """
        import pandas as pd
        
        # Build context with more data (up to 100 rows)
        if dataframe is not None and isinstance(dataframe, pd.DataFrame) and not dataframe.empty:
            # Provide comprehensive DataFrame information
            preview_rows = min(100, len(dataframe))
            
            # 列名映射（如果有）
            column_mapping_info = ""
            if table_metadata and 'column_mapping' in table_metadata:
                from utils.column_cleaner import ColumnCleaner
                cleaner = ColumnCleaner()
                column_mapping_info = cleaner.format_mapping_for_prompt(table_metadata['column_mapping']) + "\n\n"
            
            # 使用字符串拼接而不是f-string，避免用户数据中的{}导致格式化错误
            df_info = """Current DataFrame (CRITICAL - Read carefully!):
- Shape: {} rows × columns

{}** Available Columns** (use EXACTLY these names):
  {}

- **Column Data Types**:
  {}

- **Non-null Counts**:
  {}

- **Data Preview (first {} rows)**:
{}

⚠️  **CRITICAL CONSTRAINTS**:
1. ONLY use the variable name `df` (already defined)
2. ALL column names MUST be from the "Available Columns" list above
3. Do NOT create new variables like `agri_col`, `max_year`, etc.
4. Use direct indexing: df['column_name'] or df.loc[], df.iloc[]
5. Result MUST be assigned back to `df`
""".format(
                dataframe.shape,
                column_mapping_info + "- " if column_mapping_info else "",
                list(dataframe.columns),
                dataframe.dtypes.to_dict(),
                dataframe.count().to_dict(),
                preview_rows,
                dataframe.head(preview_rows).to_string()
            )
        else:
            df_info = "Current DataFrame: Empty or not available"
        
        # ⭐ 获取代码生成提示（历史成功案例和失败模式）
        current_context = self._get_table_signature(dataframe)
        hints = self.get_code_generation_hints(operator.name, current_context, max_examples=2)
        
        # 构建成功案例部分（转义花括号以便后续format使用）
        success_section = ""
        if hints["success_examples"]:
            success_section = "\n# Historical Success Examples (learn from these):\n"
            for i, example in enumerate(hints["success_examples"]):
                # 将代码中的单花括号转义为双花括号
                escaped_code = example['code'].replace('{', '{{').replace('}', '}}')
                success_section += f"\nExample {i+1}:\n```python\n{escaped_code}\n```\n"
                if example.get("explanation"):
                    escaped_expl = example['explanation'].replace('{', '{{').replace('}', '}}')
                    success_section += f"Why it worked: {escaped_expl}\n"
        
        # 构建失败模式部分
        failure_section = ""
        if hints["failure_patterns"]:
            failure_section = "\n# ⚠️  Common Failure Patterns to AVOID:\n"
            for i, pattern in enumerate(hints["failure_patterns"]):
                # 转义花括号
                escaped_error = pattern['error'].replace('{', '{{').replace('}', '}}')
                failure_section += f"\n{i+1}. Error: {escaped_error}\n"
                if pattern.get("explanation"):
                    escaped_expl = pattern['explanation'].replace('{', '{{').replace('}', '}}')
                    failure_section += f"   Cause: {escaped_expl}\n"
            
            # 添加建议
            if hints["suggestions"]:
                escaped_sugg = [s.replace('{', '{{').replace('}', '}}') for s in hints['suggestions'][:3]]
                failure_section += f"\n💡 Suggestions: {', '.join(escaped_sugg)}\n"
        
        # ⭐ SCHEMA ENHANCEMENT: 添加Schema信息提示
        schema_hint = ""
        if schema_result:
            schema_lines = []
            schema_lines.append("\n## 🎯 Schema Information (Relevant Headers for this Query):")
            
            if schema_result.selected_col_headers:
                schema_lines.append(f"\n**Relevant Columns to Consider** ({len(schema_result.selected_col_headers)}):")
                for header in schema_result.selected_col_headers[:15]:
                    schema_lines.append(f"  - {header}")
                schema_lines.append("\n💡 **Guidance**: These columns are most relevant to the query.")
                schema_lines.append("   When selecting/filtering columns, prioritize these.")
            
            if schema_result.selected_row_headers:
                schema_lines.append(f"\n**Relevant Row Headers** ({len(schema_result.selected_row_headers)}):")
                for header in schema_result.selected_row_headers[:15]:
                    schema_lines.append(f"  - {header}")
                schema_lines.append("\n💡 **Guidance**: These row headers indicate relevant data categories.")
                schema_lines.append("   Use them to filter or group data.")
            
            if schema_result.triplets:
                schema_lines.append(f"\n**Header Relationships** (hierarchical structure):")
                for triplet in schema_result.triplets[:5]:
                    schema_lines.append(f"  {triplet}")
                schema_lines.append("\n💡 **Guidance**: Use these relationships to understand data organization.")
            
            schema_lines.append("")
            schema_hint = "\n".join(schema_lines)
        
        # ⭐ ENHANCED: 添加详细的meta信息和统计数据
        meta_hint = ""
        
        # Check if we have meta_info (from meta_extractor) or metadata (from smart_processor)
        if table_metadata:
            meta_info = table_metadata.get("meta_info") or table_metadata
            
            # Build comprehensive meta hint
            if meta_info and not meta_info.get("error"):
                meta_lines = []
                meta_lines.append("\n## 📋 Table Structure Information:")
                
                # Check for different metadata formats
                if "header_rows_skipped" in meta_info:
                    # SmartTableProcessor format
                    meta_lines.append(f"- Header rows skipped: {meta_info.get('header_rows_skipped', 0)}")
                    if meta_info.get('has_merged_cells'):
                        meta_lines.append("- ⚠️  Merged cells have been preprocessed and expanded")
                    if meta_info.get('column_mapping'):
                        meta_lines.append("- Column name mapping available (see above)")
                        
                elif "data_start_row" in meta_info:
                    # MetaExtractor format
                    meta_lines.append(f"- Data starts at row {meta_info['data_start_row']}")
                    if meta_info.get('merged_cells'):
                        meta_lines.append(f"- ⚠️  {len(meta_info['merged_cells'])} merged cells detected and preprocessed")
                    if meta_info.get('hierarchy_triplets'):
                        meta_lines.append(f"- Multi-level headers: {len(set([t[0] for t in meta_info['hierarchy_triplets']]))} parent groups")
                    
                    # 添加关键列信息
                    if meta_info.get('summary'):
                        meta_lines.append(f"\n**Table Summary**: {meta_info['summary']}")
                
                meta_lines.append("\n✅ **Important**: The DataFrame `df` is already preprocessed and clean.")
                meta_lines.append("   - All merged cells have been filled")
                meta_lines.append("   - Header rows have been removed") 
                meta_lines.append("   - Column names are standardized")
                meta_lines.append("   - Work directly with `df` using the column names listed above\n")
                meta_hint = "\n".join(meta_lines)
        
        # 使用字符串模板+format而不是f-string，避免用户数据中的{产生格式化错误
        prompt_raw = """Generate Python/Pandas code for this operation.

# Context
User Query: {user_query}
Step: {step_context}

# Operation
Name: {op_name}
Description: {op_desc}
Category: {op_category}

{df_info}

{schema_hint}

{meta_hint}

{success_section}

{failure_section}

# ⚠️ CRITICAL ERROR PATTERNS TO AVOID (⭐ PHASE 1 ENHANCED)

## Error Pattern 1: Number formatting in output strings (HIGHEST PRIORITY!)
❌ WRONG: result = "The average is 45.6789"     # Too many decimals
❌ WRONG: result = "Height: 175.342857143 cm"   # Ugly long decimals
✅ CORRECT: result = f"The average is {{round(num, 2)}}"    # Use round()
✅ CORRECT: result = f"Height is {{int(height)}} cm"       # Use int() for whole numbers
✅ CORRECT: avg_value = round(df['col'].mean(), 3)         # Round first, then use
                result = f"Average: {{avg_value}}"

## Error Pattern 2: Using undefined variables
❌ WRONG: df = df[df['Year'] == max_year]  # max_year not defined!
✅ CORRECT: 
   max_year = df['Year'].max()  # Define first
   df = df[df['Year'] == max_year]

## Error Pattern 3: Returning dict instead of DataFrame
❌ WRONG: df = {{'Region': ['A'], 'Sales': [100]}}  # This is a dict!
✅ CORRECT: df = pd.DataFrame({{'Region': ['A'], 'Sales': [100]}})

## Error Pattern 4: groupby without reset_index
❌ WRONG: df = df.groupby('Region').sum()  # Returns non-DataFrame
✅ CORRECT: df = df.groupby('Region').sum().reset_index()

## Error Pattern 5: Using variables before definition
❌ WRONG: result_str = f"Height is {{height}}"  # height not defined yet!
✅ CORRECT:
   height = df['Height'].mean()
   result_str = f"Height is {{round(height, 2)}}"

# Requirements (CRITICAL - Follow strictly!)
1. **Input**: `df` is a pandas DataFrame (already loaded and available)
2. **Output**: **MUST** assign result back to `df` as a pandas DataFrame
   - ✅ CORRECT: `df = df.groupby(...).agg(...).reset_index()`
   - ✅ CORRECT: `df = pd.DataFrame({{'col1': values1, 'col2': values2}})`
   - ❌ WRONG: `df = {{'col1': values1, 'col2': values2}}` (this is a dict, not DataFrame!)
3. **Critical DataFrame Rule**:
   - **NEVER** assign a dictionary to `df`
   - **ALWAYS** use `pd.DataFrame()` to create DataFrames from dictionaries
   - **ALWAYS** use `.reset_index()` after groupby operations
4. **ABSOLUTE PROHIBITION on Format Specifiers**:
   - **NEVER EVER** use {{variable:.Xf}} in any string
   - **ALWAYS** use round(variable, X) instead
   - This is the #1 cause of execution failures
5. **Allowed libraries**: pandas (as `pd`), numpy (as `np`)
6. **Variable constraints**:
   - ALL variables must be defined before use
   - Use EXACT column names from the "Available Columns" list above
7. **Self-Check Checklist** (⭐ VERIFY BEFORE SUBMITTING):
   □ Did I define ALL variables before using them?
   □ Does my code end with `df` being a DataFrame (not dict/Series)?
   □ Did I use round() instead of {{:.Xf}} format specifiers?
   □ Did I use reset_index() after groupby operations?
   □ Did I only use columns from "Available Columns"?

# Output Format
   ```python
   # ✅ GOOD - Direct operation returning DataFrame
   df = df[df['Year'] > 2000]
   df = df.sort_values('Agriculture', ascending=False)
   df = df.groupby('Region').agg({{'Sales': 'sum'}}).reset_index()  # MUST use reset_index()!
   
   # ✅ GOOD - Creating DataFrame from aggregation
   result_dict = {{'Region': ['A', 'B'], 'Total': [100, 200]}}
   df = pd.DataFrame(result_dict)  # Convert dict to DataFrame!
   
   # ✅ GOOD - Proper formatting with defined variables
   value = df['Score'].mean()
   df = pd.DataFrame({{'Mean': [round(value, 2)]}})  # Define THEN use!
   
   # ❌ BAD - Using undefined variables
   df = df[df['Year'] == max_year]  # max_year not defined!
   
   # ❌ BAD - Assigning dictionary instead of DataFrame
   df = {{'Region': ['A', 'B'], 'Total': [100, 200]}}  # WRONG! This is dict, not DataFrame!
   
   # ❌ BAD - Using undefined variables
   result_str = f"The height is {{height}}"  # height not defined! Will cause error!
   ```
8. **Edge cases**: Handle NaN, empty df, missing columns
9. **Learn from success/failure examples above**
10. **Final check**: Your code MUST end with `df` being a pandas DataFrame, not a dict/list/series

# Output Format
Output ONLY the Python code in markdown format:
```python
# Your code here
df = df[...]  # example
```

Code:
"""
        
        # 现在用.format()填充变量，避免f-string问题
        prompt = prompt_raw.format(
            user_query=user_query,
            step_context=step_context,
            op_name=operator.name,
            op_desc=operator.description,
            op_category=operator.category.value,
            df_info=df_info,
            schema_hint=schema_hint,
            meta_hint=meta_hint,
            success_section=success_section,
            failure_section=failure_section
        )
        
        try:
            raw_response = self.llm_client.call_api(prompt)
            code = self._clean_code(raw_response)
            return code, prompt
        except Exception as e:
            # Fallback: use simple pass statement
            fallback_code = "# Error generating code, skipping\npass"
            return fallback_code, prompt
    
    def _generate_code_with_stages(
        self,
        operator: Operator,
        dataframe,
        user_query: str,
        table_metadata: Dict[str, Any],
        step_context: str = "",
        schema_result=None,
        max_refinement_rounds: int = 2
    ) -> Tuple[str, str, Optional[Dict]]:
        """
        ⭐ MULTI-STAGE CODE GENERATION with Understanding-Generation-Reflection
        
        借鉴Decompose-Align-Reason框架，分3个阶段：
        1. Stage 1: Understanding & Alignment - 理解问题并对齐到表格
        2. Stage 2: Code Generation - 基于理解生成代码
        3. Stage 3: Reflection & Refinement - 验证结果并反思改进
        
        Args:
            max_refinement_rounds: 最多refinement次数（默认2次）
        
        Returns:
            (code, prompt, reflection_result)
        """
        import pandas as pd
        import json
        
        feedback = None
        last_code = None
        last_prompt = None
        last_reflection = None
        
        for round_idx in range(max_refinement_rounds + 1):
            print(f"    🔄 Multi-Stage Round {round_idx + 1}/{max_refinement_rounds + 1}")
            
            # ==================== Stage 1: Understanding & Alignment ====================
            print(f"       Stage 1: Understanding & Alignment...")
            understanding = self._stage1_understand_and_align(
                operator=operator,
                dataframe=dataframe,
                user_query=user_query,
                table_metadata=table_metadata,
                schema_result=schema_result,
                refinement_feedback=feedback
            )
            
            if not understanding:
                print(f"       ⚠️  Stage 1 failed, falling back to direct generation")
                return self._generate_code(operator, dataframe, user_query, table_metadata, step_context, schema_result)
            
            # 验证alignment
            if not self._validate_alignment(understanding, dataframe):
                print(f"       ⚠️  Alignment validation failed")
                if round_idx < max_refinement_rounds:
                    feedback = {"error": "Alignment validation failed", "understanding": understanding}
                    continue
                else:
                    # 最后一次也失败，fallback
                    return self._generate_code(operator, dataframe, user_query, table_metadata, step_context, schema_result)
            
            print(f"       ✓ Understanding: {understanding.get('task_understanding', {}).get('intent', 'N/A')[:60]}...")
            
            # ==================== Stage 2: Code Generation ====================
            print(f"       Stage 2: Code Generation...")
            code, code_prompt = self._stage2_generate_code(
                understanding=understanding,
                operator=operator,
                dataframe=dataframe,
                user_query=user_query,
                table_metadata=table_metadata,
                schema_result=schema_result
            )
            
            last_code = code
            last_prompt = code_prompt
            
            # 执行代码
            exec_result = self._execute_code(code, dataframe)
            
            if not exec_result["success"]:
                print(f"       ❌ Execution failed: {exec_result.get('error', 'Unknown')[:60]}")
                # 执行失败，直接返回（语法错误无法通过refinement修复）
                return code, code_prompt, None
            
            print(f"       ✓ Code executed successfully")
            
            # ==================== Stage 3: Reflection & Refinement ====================
            print(f"       Stage 3: Reflection & Refinement...")
            reflection = self._stage3_reflect_and_refine(
                understanding=understanding,
                code=code,
                exec_result=exec_result,
                dataframe=dataframe,
                user_query=user_query
            )
            
            last_reflection = reflection
            
            if not reflection:
                print(f"       ⚠️  Reflection failed, accepting result")
                return code, code_prompt, None
            
            # 检查是否需要refinement
            need_refinement = reflection.get("need_refinement", False)
            confidence = reflection.get("confidence", 0.0)
            
            print(f"       Confidence: {confidence:.2f}, Need refinement: {need_refinement}")
            
            if not need_refinement:
                print(f"       ✓ Validation passed, accepting result")
                return code, code_prompt, reflection
            
            # 需要refinement
            if round_idx < max_refinement_rounds:
                print(f"       🔄 Refinement needed, preparing next round...")
                feedback = {
                    "previous_result": exec_result,
                    "sanity_checks": reflection.get("sanity_checks", {}),
                    "hypothesis": reflection.get("refinement_hypothesis", "Unknown issue")
                }
            else:
                print(f"       ⚠️  Max refinement rounds reached, accepting last result")
                return code, code_prompt, reflection
        
        # Should not reach here
        return last_code, last_prompt, last_reflection
    
    def _stage1_understand_and_align(
        self,
        operator: Operator,
        dataframe,
        user_query: str,
        table_metadata: Dict[str, Any],
        schema_result=None,
        refinement_feedback=None
    ) -> Optional[Dict]:
        """
        Stage 1: Understanding & Alignment
        
        让LLM理解任务并对齐到表格数据
        
        Returns:
            Dict with keys: task_understanding, data_alignment, reasoning_plan
        """
        import pandas as pd
        import json
        
        if dataframe is None or not isinstance(dataframe, pd.DataFrame) or dataframe.empty:
            return None
        
        # 采样数据（前10行 + 统计信息）
        sample_rows = min(10, len(dataframe))
        sample_data = dataframe.head(sample_rows).to_string()
        
        # 列统计信息
        column_stats = {}
        for col in dataframe.columns:
            if pd.api.types.is_numeric_dtype(dataframe[col]):
                sample_values = dataframe[col].dropna().head(5).tolist()
                column_stats[col] = {
                    "type": str(dataframe[col].dtype),
                    "sample_values": sample_values,
                    "min": float(dataframe[col].min()) if not dataframe[col].isna().all() else None,
                    "max": float(dataframe[col].max()) if not dataframe[col].isna().all() else None,
                    "mean": float(dataframe[col].mean()) if not dataframe[col].isna().all() else None
                }
            else:
                sample_values = dataframe[col].dropna().head(5).tolist()
                column_stats[col] = {
                    "type": str(dataframe[col].dtype),
                    "sample_values": sample_values,
                    "unique_count": int(dataframe[col].nunique())
                }
        
        # Schema信息
        schema_hint = ""
        if schema_result and schema_result.selected_col_headers:
            schema_hint = f"\n**Schema-Selected Relevant Columns**: {', '.join(schema_result.selected_col_headers[:10])}"
        
        # Refinement feedback
        feedback_hint = ""
        if refinement_feedback:
            feedback_hint = f"""
## 🔄 Refinement Feedback from Previous Attempt

Previous attempt had issues. Please reconsider your understanding:

**Previous Issue**: {refinement_feedback.get('hypothesis', 'Unknown')}

**Sanity Checks that Failed**:
{json.dumps(refinement_feedback.get('sanity_checks', {}), indent=2)}

Please re-examine the data and provide a corrected understanding.
"""
        
        prompt = f"""# Stage 1: Understanding & Alignment

You are analyzing a table to understand how to solve a task. Your goal is to:
1. **Deeply understand** what the task is asking
2. **Carefully examine** the table data and identify relevant columns
3. **Observe** the scale, magnitude, and nature of the data values
4. **Decompose** the task into clear, logical steps
5. **Plan** the reasoning approach based on actual data characteristics

## Task Information

**User Query**: {user_query}

**Operator**: {operator.name}
**Description**: {operator.description}

## Table Information

**Available Columns**: {list(dataframe.columns)}

**Column Statistics** (CRITICAL - Read each column carefully):
{json.dumps(column_stats, indent=2)}

**Data Sample (first {sample_rows} rows)** - Examine these values:
{sample_data}
{schema_hint}
{feedback_hint}

## 🔍 Your Analysis Task

Provide a structured understanding in JSON format. You MUST:

### 1. **task_understanding** 
Deeply understand what the query is asking:
   - **keywords**: Extract key terms from the query (e.g., ["Agriculture", "maximum", "2006-2007"])
   - **intent**: Clear description of what needs to be done (e.g., "Find the value of Agriculture in the year with maximum Agriculture")
   - **expected_result_type**: "single_number", "list", "percentage", "dataframe", "comparison", etc.
   - **decomposition**: Break down the task into 2-4 logical sub-tasks
     Example: ["1. Find year with max Agriculture value", "2. Get Agriculture value for that year"]

### 2. **data_alignment**
Examine the data and identify relevant information:
   - **relevant_columns**: List of dicts, each with:
     - **name**: Exact column name from the table
     - **sample_values**: 3-5 actual values from the column (copy from the data)
     - **data_type**: The column's dtype (e.g., "int64", "float64", "object")
     - **scale_observation**: YOUR CRITICAL OBSERVATION about the scale
       * Look at the sample_values - are they 3-digit (e.g., 342, 456)? 5-digit (e.g., 14342)? 
       * Example observations:
         - "3-digit integers (342, 456, 523), appear to be actual counts or percentages"
         - "5-digit floats (14342.90, 20936.60), possibly in thousands or millions"
         - "Small decimals (0.23, 0.45), likely percentages in 0-1 range"
       * DO NOT assume units like "thousands" unless values are very large (>100,000)
     - **purpose**: Why this column is relevant to the task

### 3. **reasoning_plan**
Create a step-by-step plan:
   - **step1, step2, step3, ...**: Clear, executable steps
     * Each step should be concrete (e.g., "Filter df where Year==2006" NOT "Find relevant year")
     * Include what operations to use (filter, groupby, max, sum, etc.)
   - **expected_output_scale**: Based on your scale_observation, what range/magnitude do you expect?
     * Example: "3-digit number similar to input values (300-600 range)"
     * Example: "5-digit number, sum of multiple values (10000-50000 range)"
   - **verification_check**: How to verify the result is reasonable
     * Example: "Result should be one of the values present in Agriculture column"
     * Example: "Result should be <= sum of all values in the column"

## ⚠️ CRITICAL INSTRUCTIONS

1. **Examine sample_values carefully**: 
   - If you see [342, 456, 523, 389], these are 3-digit numbers → likely actual values
   - If you see [14342.90, 20936.60, 25789.30], these are 5-digit → possibly thousands/millions
   - If you see [0.23, 0.45, 0.67], these are decimals → likely percentages

2. **Do NOT make assumptions about units**:
   - DON'T assume "thousands" without evidence
   - DON'T multiply/divide by 1000 unless explicitly stated in query or obvious from data

3. **Decompose complex tasks**:
   - If query asks "value in year with maximum", break into: [1) find year with max, 2) get value for that year]
   - If query asks for comparison, break into: [1) get first value, 2) get second value, 3) compare]

4. **Be specific in reasoning_plan**:
   - BAD: "Find the relevant data"
   - GOOD: "Filter df[df['Year'] == target_year] to get Agriculture value"

Output ONLY the JSON, no other text:
```json
{{
  "task_understanding": {{
    "keywords": [...],
    "intent": "...",
    "expected_result_type": "...",
    "decomposition": ["step1", "step2", ...]
  }},
  "data_alignment": {{
    "relevant_columns": [
      {{
        "name": "...",
        "sample_values": [...],
        "data_type": "...",
        "scale_observation": "CRITICAL: Your observation about magnitude",
        "purpose": "..."
      }}
    ]
  }},
  "reasoning_plan": {{
    "step1": "...",
    "step2": "...",
    "expected_output_scale": "...",
    "verification_check": "..."
  }}
}}
```
"""
        
        try:
            response = self.llm_client.call_api(prompt)
            
            # Parse JSON
            understanding = self._parse_json_safely(response)
            
            if not understanding:
                print(f"         ⚠️  Failed to parse Stage 1 response")
                return None
            
            # 验证必需字段
            required_keys = ["task_understanding", "data_alignment", "reasoning_plan"]
            if not all(key in understanding for key in required_keys):
                print(f"         ⚠️  Stage 1 response missing required keys")
                return None
            
            return understanding
            
        except Exception as e:
            print(f"         ❌ Stage 1 error: {e}")
            return None
    
    def _validate_alignment(self, understanding: Dict, dataframe) -> bool:
        """验证Stage 1的alignment是否合理"""
        import pandas as pd
        
        try:
            data_alignment = understanding.get("data_alignment", {})
            relevant_columns = data_alignment.get("relevant_columns", [])
            
            if not relevant_columns:
                return True  # 没有指定列，接受
            
            # 检查列名是否存在
            for col_info in relevant_columns:
                col_name = col_info.get("name", "")
                if col_name not in dataframe.columns:
                    print(f"         ⚠️  Column '{col_name}' not in dataframe")
                    return False
            
            return True
            
        except Exception as e:
            print(f"         ⚠️  Validation error: {e}")
            return False
    
    def _stage2_generate_code(
        self,
        understanding: Dict,
        operator: Operator,
        dataframe,
        user_query: str,
        table_metadata: Dict[str, Any],
        schema_result=None
    ) -> Tuple[str, str]:
        """
        Stage 2: Code Generation
        
        基于Stage 1的理解生成代码
        """
        import pandas as pd
        import json
        
        # 提取理解信息
        task_understanding = understanding.get("task_understanding", {})
        data_alignment = understanding.get("data_alignment", {})
        reasoning_plan = understanding.get("reasoning_plan", {})
        
        intent = task_understanding.get("intent", "Unknown")
        relevant_columns = data_alignment.get("relevant_columns", [])
        
        # 构建理解摘要
        understanding_summary = f"""## Understanding from Stage 1

**Task Intent**: {intent}

**Relevant Columns**:
"""
        for col_info in relevant_columns[:5]:
            col_name = col_info.get("name", "")
            scale_obs = col_info.get("scale_observation", "")
            purpose = col_info.get("purpose", "")
            understanding_summary += f"  - {col_name}: {scale_obs} ({purpose})\n"
        
        understanding_summary += f"\n**Reasoning Plan**:\n"
        for key, value in reasoning_plan.items():
            if key.startswith("step"):
                understanding_summary += f"  {key}: {value}\n"
        
        expected_scale = reasoning_plan.get("expected_output_scale", "Unknown")
        understanding_summary += f"\n**Expected Output Scale**: {expected_scale}\n"
        
        # DataFrame信息（简化版，因为Stage 1已经分析过了）
        df_info = f"""**DataFrame Shape**: {dataframe.shape}
**Available Columns**: {list(dataframe.columns)}
**First 5 rows**:
{dataframe.head(5).to_string()}
"""
        
        prompt = f"""# Stage 2: Code Generation

Based on the understanding from Stage 1, generate Python/Pandas code to solve the task.

{understanding_summary}

## DataFrame Information

{df_info}

## 🔍 CRITICAL: Data Analysis Approach

You MUST deeply analyze the table structure and data characteristics:

1. **Examine the data carefully**:
   - Look at the sample values in relevant columns
   - Observe the scale and magnitude of numbers (are they 3-digit? 5-digit? decimals?)
   - Check data types and patterns

2. **Use df and pandas operations**:
   - Access columns using df['column_name']
   - Use df.loc[], df.iloc[] for row/column selection
   - Apply filtering: df[df['column'] > value]
   - Use groupby/agg for aggregation
   - Use .sum(), .mean(), .max(), .min() for statistics

3. **Leverage openpyxl concepts when needed**:
   - Think about cell references (row/column indices)
   - Consider merged cells and hierarchical headers (already preprocessed in df)
   - Use df.shape to understand table dimensions

4. **Decompose complex tasks**:
   - Break down into multiple clear steps
   - Define intermediate variables when needed
   - Add comments explaining each major step

## ⚠️ Code Generation Rules (MUST FOLLOW)

1. **Use the understanding above**: Your code MUST follow the reasoning plan from Stage 1
2. **Respect the scale observations**: 
   - If Stage 1 says "3-digit numbers, likely actual counts", do NOT multiply by 1000
   - If Stage 1 says "values in thousands range", interpret accordingly
   - NEVER assume units without evidence in the data
3. **MUST assign result to `df`**: Final result must be a pandas DataFrame assigned to `df`
4. **NO format specifiers**: Use round() instead of {{:.Xf}}
5. **Define before use**: ALL variables must be defined before use
6. **Decompose properly**: 
   - If task requires multiple steps, break them down clearly
   - Use intermediate variables for clarity
   - Example:
     ```python
     # Step 1: Filter relevant data
     filtered_df = df[df['Year'] == 2020]
     
     # Step 2: Calculate statistic
     result_value = filtered_df['Sales'].sum()
     
     # Step 3: Create result DataFrame
     df = pd.DataFrame({{'Result': [result_value]}})
     ```

## 📊 Example Analysis Patterns

**Pattern 1: Finding maximum/minimum**
```python
# Find the year with maximum value
max_year = df['Year'].max()
result_df = df[df['Year'] == max_year]
df = result_df
```

**Pattern 2: Filtering and aggregating**
```python
# Filter by condition
filtered = df[df['Category'] == 'A']

# Aggregate
result = filtered['Value'].sum()

# Create result DataFrame
df = pd.DataFrame({{'Total': [result]}})
```

**Pattern 3: Multi-step calculation**
```python
# Step 1: Get relevant rows
target_rows = df[df['Country'] == 'USA']

# Step 2: Calculate metric
avg_value = target_rows['GDP'].mean()

# Step 3: Format result
df = pd.DataFrame({{'Average_GDP': [round(avg_value, 2)]}})
```

## Output Format

Output ONLY the Python code in markdown format:
```python
# Based on Stage 1 understanding: {intent}
# Reasoning: [Brief explanation of your approach]

# Your code here (with clear step-by-step comments)
# Step 1: ...
df = ...
```

Code:
"""
        
        # 现在用.format()填充变量，避免f-string问题
        prompt = prompt_raw.format(
            user_query=user_query,
            step_context=step_context,
            op_name=operator.name,
            op_desc=operator.description,
            op_category=operator.category.value,
            df_info=df_info,
            schema_hint=schema_hint,
            meta_hint=meta_hint,
            success_section=success_section,
            failure_section=failure_section
        )
        
        try:
            response = self.llm_client.call_api(prompt)
            code = self._clean_code(response)
            return code, prompt
        except Exception as e:
            fallback_code = "# Error in Stage 2\npass"
            return fallback_code, prompt
    
    def _stage3_reflect_and_refine(
        self,
        understanding: Dict,
        code: str,
        exec_result: Dict,
        dataframe,
        user_query: str
    ) -> Optional[Dict]:
        """
        Stage 3: Reflection & Refinement
        
        验证执行结果是否合理
        
        Returns:
            Dict with keys: sanity_checks, confidence, need_refinement, refinement_hypothesis
        """
        import pandas as pd
        import json
        
        result_df = exec_result.get("dataframe")
        if result_df is None or not isinstance(result_df, pd.DataFrame):
            return None
        
        # 提取expected信息
        task_understanding = understanding.get("task_understanding", {})
        reasoning_plan = understanding.get("reasoning_plan", {})
        
        expected_result_type = task_understanding.get("expected_result_type", "unknown")
        expected_scale = reasoning_plan.get("expected_output_scale", "unknown")
        
        # 提取实际结果
        actual_result_summary = f"Shape: {result_df.shape}, "
        if result_df.shape[0] == 1 and result_df.shape[1] == 1:
            actual_value = result_df.iloc[0, 0]
            actual_result_summary += f"Single value: {actual_value}"
        else:
            actual_result_summary += f"Columns: {list(result_df.columns)}"
        
        prompt = f"""# Stage 3: Reflection & Refinement

Verify if the execution result matches the expected understanding.

## Expected (from Stage 1)

**Task Intent**: {task_understanding.get('intent', 'Unknown')}
**Expected Result Type**: {expected_result_type}
**Expected Output Scale**: {expected_scale}

## Actual Result

**Result Summary**: {actual_result_summary}

**Result Preview**:
{result_df.head(10).to_string()}

## Your Task

Perform sanity checks and determine if the result is reasonable:

1. **Scale Check**: Does the result's magnitude match the expected scale?
   - If expected "3-digit number" but got 764000 (6-digit), that's a FAILURE
   - If expected "thousands range" and got 1575, that's OK

2. **Type Check**: Does the result type match expectations?
   - If expected "single_number" and got DataFrame with 1 row, that's OK
   - If expected "list" and got single number, that's a failure

3. **Logic Check**: Does the result make logical sense given the data?

Provide a structured response in JSON format:

```json
{{
  "execution_status": "success",
  "sanity_checks": {{
    "scale_check": {{
      "expected": "...",
      "actual": "...",
      "status": "✅ passed" or "❌ failed" or "⚠️ uncertain"
    }},
    "type_check": {{
      "expected": "...",
      "actual": "...",
      "status": "✅ passed" or "❌ failed"
    }},
    "logic_check": {{
      "reasoning": "...",
      "status": "✅ passed" or "❌ failed" or "⚠️ uncertain"
    }}
  }},
  "confidence": 0.0 to 1.0,
  "need_refinement": true or false,
  "refinement_hypothesis": "If need_refinement=true, explain what might be wrong"
}}
```

**Decision Rule**: Set `need_refinement=true` if ANY sanity check has status "❌ failed".

Output ONLY the JSON:
"""
        
        try:
            response = self.llm_client.call_api(prompt)
            reflection = self._parse_json_safely(response)
            
            if not reflection:
                print(f"         ⚠️  Failed to parse Stage 3 response")
                return None
            
            return reflection
            
        except Exception as e:
            print(f"         ❌ Stage 3 error: {e}")
            return None
    
    def _parse_json_safely(self, text: str) -> Optional[Dict]:
        """从文本中安全地解析JSON"""
        import json
        import re
        
        if not text:
            return None
        
        # 尝试直接解析
        try:
            return json.loads(text)
        except:
            pass
        
        # 尝试提取代码块中的JSON
        json_pattern = r'```(?:json)?\s*(.*?)```'
        matches = re.findall(json_pattern, text, re.DOTALL)
        
        if matches:
            for match in matches:
                try:
                    return json.loads(match.strip())
                except:
                    continue
        
        # 尝试找到第一个 { 到最后一个 }
        try:
            first_brace = text.index('{')
            last_brace = text.rindex('}')
            json_str = text[first_brace:last_brace+1]
            return json.loads(json_str)
        except:
            pass
        
        return None
    
    def _clean_code(self, raw_code: str) -> str:
        """Extract and clean code from LLM response"""
        # ⭐ PHASE 1 FIX: 类型安全检查
        if not isinstance(raw_code, str):
            print(f"    ⚠️  _clean_code received non-string: {type(raw_code)}")
            return "# Error: LLM returned non-string response\npass"
        
        code = raw_code.strip()
        if not code:
            print(f"    ⚠️  _clean_code received empty string")
            return "# Error: Empty code\npass"
        
        # Extract from markdown code blocks
        code_block_pattern = r'```(?:python)?\s*(.*?)```'
        matches = re.findall(code_block_pattern, code, re.DOTALL)
        
        if matches:
            code = '\n'.join(match.strip() for match in matches)
        else:
            # Simple cleanup
            if code.startswith("```python"):
                code = code[9:].strip()
            elif code.startswith("```"):
                code = code[3:].strip()
            if code.endswith("```"):
                code = code[:-3].strip()
        
        # Remove file reading statements (safety)
        if "pd.read_excel" in code or "pd.read_csv" in code:
            lines = code.split('\n')
            code = '\n'.join([l for l in lines if 'read_excel' not in l and 'read_csv' not in l])
        
        return code.strip()
    
    def _execute_code(
        self,
        code: str,
        dataframe
    ) -> Dict[str, Any]:
        """
        Execute generated code safely.
        
        Returns:
            Dict with keys: success (bool), dataframe (pd.DataFrame), error (str)
        """
        import pandas as pd
        import numpy as np
        
        # ⭐ PHASE 1 FIX: 验证输入
        if not code or not isinstance(code, str):
            return {
                "success": False,
                "error": "Empty or invalid code",
                "dataframe": dataframe if dataframe is not None else pd.DataFrame()
            }
        
        code = code.strip()
        if code == "pass" or code.startswith("# Error:"):
            return {
                "success": False,
                "error": "Code generation failed",
                "dataframe": dataframe if dataframe is not None else pd.DataFrame()
            }
        
        # ⭐ PHASE 1 FIX: 代码结构验证
        validation_result = self._validate_code_structure(code)
        if not validation_result[0]:
            return {
                "success": False,
                "error": f"Code validation failed: {validation_result[1]}",
                "dataframe": dataframe if dataframe is not None else pd.DataFrame()
            }
        
        # Safety checks
        forbidden = ["exit(", "quit(", "sys.exit", "os.system", "subprocess", "__import__", "eval(", "exec("]
        for kw in forbidden:
            if kw in code:
                return {
                    "success": False,
                    "error": f"Forbidden keyword: {kw}"
                }
        
        # Prepare execution environment
        if dataframe is None or not isinstance(dataframe, pd.DataFrame):
            dataframe = pd.DataFrame()
        
        try:
            df_copy = dataframe.copy()
        except Exception as e:
            df_copy = dataframe
        
        local_vars = {
            "df": df_copy,
            "pd": pd,
            "np": np
        }
        
        global_vars = {
            "pd": pd,
            "np": np,
            "__builtins__": __builtins__
        }
        
        # Execute
        try:
            exec(code, global_vars, local_vars)
            result_df = local_vars.get("df", dataframe)
            
            # ⚠️ CRITICAL FIX: Auto-convert dict to DataFrame
            if isinstance(result_df, dict):
                try:
                    result_df = pd.DataFrame(result_df)
                    print(f"    ⚠️  Auto-converted dict to DataFrame (shape: {result_df.shape})")
                except Exception as e:
                    return {
                        "success": False,
                        "error": f"Result is a dict but cannot convert to DataFrame: {e}",
                        "dataframe": dataframe
                    }
            
            # Ensure result is DataFrame
            if not isinstance(result_df, pd.DataFrame):
                return {
                    "success": False,
                    "error": f"Code must assign a pandas DataFrame to 'df', got {type(result_df).__name__}",
                    "dataframe": dataframe
                }
            
            return {
                "success": True,
                "dataframe": result_df
            }
        
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "dataframe": dataframe  # Return original on failure
            }
    
    def _validate_code_structure(self, code: str) -> Tuple[bool, str]:
        """
        ⭐ PHASE 1: 验证代码结构，避免常见错误
        
        Returns:
            (is_valid, error_message)
        """
        # 检查1: 是否有赋值给df
        if 'df =' not in code and 'df=' not in code:
            return False, "Code doesn't assign result to 'df'"
        
        # 检查2: 危险的f-string格式化 (会导致format error)
        # 匹配模式: :.2f" 或 :.3f} 等
        if re.search(r':\.\d+f["\'}]', code):
            return False, "Code contains f-string format specifier (:.Xf) - use round() instead"
        
        # 检查3: 常见的未定义变量模式
        dangerous_vars = {
            r'\bmax_year\b': 'max_year',
            r'\bmin_year\b': 'min_year',
            r'\btarget_row\b': 'target_row',
            r'\bagri_col\b': 'agri_col',
            r'\bheight\b(?!.*height\s*=)': 'height (may be undefined)'
        }
        
        for pattern, var_name in dangerous_vars.items():
            if re.search(pattern, code):
                # 检查变量是否在使用前定义
                lines_before_use = code[:code.find(var_name)].split('\n') if var_name in code else []
                is_defined = any(f'{var_name} =' in line or f'{var_name}=' in line for line in lines_before_use)
                if not is_defined:
                    print(f"    ⚠️  Warning: Variable '{var_name}' may be used before definition")
                    # 不阻止，只警告
        
        return True, "OK"
    
    def get_memory_summary(self) -> Dict[str, Any]:
        """Get summary of execution memory"""
        if not self.memory:
            return {
                "total_nodes": 0,
                "success_rate": 0.0,
                "avg_reward": 0.0
            }
        
        success_count = sum(1 for node in self.memory if node.success)
        total_reward = sum(node.reward_vector.total_score for node in self.memory if node.reward_vector)
        
        return {
            "total_nodes": len(self.memory),
            "success_count": success_count,
            "failure_count": len(self.memory) - success_count,
            "success_rate": success_count / len(self.memory) if self.memory else 0.0,
            "avg_reward": total_reward / len(self.memory) if self.memory else 0.0,
            "operators_executed": [node.operator_name for node in self.memory]
        }
    
    def clear_memory(self):
        """Clear current memory (but keep persistent)"""
        self.memory = []
    
    def save_memory_to_persistent(self, session_id: str):
        """Save current memory to persistent storage"""
        self.persistent_memory[session_id] = self.memory.copy()
    
    def load_memory_from_persistent(self, session_id: str):
        """Load memory from persistent storage"""
        if session_id in self.persistent_memory:
            self.memory = self.persistent_memory[session_id].copy()
    
    def _aggregate_sub_rewards(self, reward: RewardVector) -> float:
        """
        Aggregate sub-rewards into a single scalar using system-level weights.
        
        CRITICAL: LLM does NOT participate in this weighting.
        This is purely system-level aggregation.
        
        Formula (as specified):
            reward = (
                + 2.0 * execution_success
                + 3.0 * query_satisfaction
                + 1.5 * code_reasonableness
                + 1.0 * efficiency
                - 3.0 * error_severity
            )
        """
        from src.core.dtr_structures import RewardVector as RV
        
        reward_dict = {
            "execution_success": reward.execution_success,
            "query_satisfaction": reward.query_satisfaction,
            "code_reasonableness": reward.code_reasonableness,
            "efficiency": reward.efficiency,
            "error_severity": reward.error_severity
        }
        
        # Use the static aggregation function
        aggregated = RV.aggregate_reward(reward_dict)
        
        return aggregated
    
    def _update_smg_context(
        self,
        operator: Operator,
        context: str,
        reward_vector: RewardVector,
        success: bool
    ):
        """
        Update SMG's context-action memory for future planning.
        
        This allows SMG to remember:
        - Which actions work well in which contexts
        - High error_severity cases → insert CLEAN/VALIDATE
        - Successful patterns → increase P(a|s) in future MCTS
        
        Storage format:
            context_key = f"{operator.name}+{context_signature}"
            value = {
                "success_count": int,
                "failure_count": int,
                "avg_reward": float,
                "error_severity_history": List[float],
                "suggestions": List[str]  # e.g., ["insert_validation", "add_cleaning"]
            }
        """
        # Create context key
        context_key = f"{operator.name}+{context}"
        
        # Initialize if not exists
        if context_key not in self.persistent_memory:
            self.persistent_memory[context_key] = {
                "success_count": 0,
                "failure_count": 0,
                "total_reward": 0.0,
                "execution_count": 0,
                "error_severity_history": [],
                "suggestions": []
            }
        
        # Update statistics
        record = self.persistent_memory[context_key]
        record["execution_count"] += 1
        record["total_reward"] += reward_vector.total_score
        
        if success:
            record["success_count"] += 1
        else:
            record["failure_count"] += 1
            record["error_severity_history"].append(reward_vector.error_severity)
            
            # If error_severity is high, suggest preprocessing
            if reward_vector.error_severity > 0.5:
                if "missing previous quarter data" in reward_vector.explanation.lower():
                    if "insert_time_validation" not in record["suggestions"]:
                        record["suggestions"].append("insert_time_validation")
                elif "missing" in reward_vector.explanation.lower() or "null" in reward_vector.explanation.lower():
                    if "insert_data_cleaning" not in record["suggestions"]:
                        record["suggestions"].append("insert_data_cleaning")
    
    def _get_table_signature(self, df) -> str:
        """
        Generate a compact signature for the current table state.
        Used as context for SMG memory updates.
        
        Returns a string like: "shape(100,5)_types(3float_2str)"
        """
        import pandas as pd
        
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return "empty"
        
        # Count column types
        type_counts = {}
        for dtype in df.dtypes:
            dtype_str = str(dtype)
            if "int" in dtype_str:
                type_name = "int"
            elif "float" in dtype_str:
                type_name = "float"
            elif "object" in dtype_str or "str" in dtype_str:
                type_name = "str"
            elif "datetime" in dtype_str:
                type_name = "datetime"
            else:
                type_name = "other"
            
            type_counts[type_name] = type_counts.get(type_name, 0) + 1
        
        # Build signature
        shape_str = f"shape{df.shape}"
        types_str = "_".join([f"{count}{tname}" for tname, count in sorted(type_counts.items())])
        
        return f"{shape_str}_types({types_str})"
    
    def get_context_suggestions(self, operator_name: str, context: str) -> List[str]:
        """
        Get suggestions for an operator in a given context based on historical data.
        
        Returns:
            List of suggestions like ["insert_validation", "add_cleaning"]
        """
        context_key = f"{operator_name}+{context}"
        
        if context_key in self.persistent_memory:
            return self.persistent_memory[context_key].get("suggestions", [])
        
        return []
    
    def get_success_rate(self, operator_name: str, context: str) -> float:
        """
        Get historical success rate for an operator in a context.
        Can be used to adjust P(a|s) in MCTS.
        
        Returns:
            Success rate 0.0-1.0, or 0.5 if no history
        """
        context_key = f"{operator_name}+{context}"
        
        if context_key in self.persistent_memory:
            record = self.persistent_memory[context_key]
            total = record["success_count"] + record["failure_count"]
            if total > 0:
                return record["success_count"] / total
        
        return 0.5  # No history, assume neutral
    
    def get_experience_summary_for_llm(
        self,
        query_type: str = None,
        max_entries: int = 5
    ) -> str:
        """
        生成文字格式的经验摘要，用于传入LLM（ADO和重规划阶段）。
        
        这个方法在两个关键时刻被调用：
        1. ADO第一次规划时 - 帮助LLM选择更合适的operators
        2. 重规划时 - 告诉LLM哪些路径失败了，应该怎么调整
        
        Args:
            query_type: 可选的query类型过滤
            max_entries: 最多返回多少条经验
        
        Returns:
            格式化的经验摘要字符串
        """
        if not self.persistent_memory:
            return ""
        
        summary_lines = []
        
        # 按执行次数和成功率排序
        sorted_records = []
        for key, record in self.persistent_memory.items():
            if record.get("execution_count", 0) < 2:
                continue  # 跳过样本太少的
            
            operator, context = key.split("+", 1) if "+" in key else (key, "")
            success_rate = record["success_count"] / max(record["execution_count"], 1)
            
            sorted_records.append({
                "operator": operator,
                "context": context,
                "success_rate": success_rate,
                "record": record
            })
        
        sorted_records.sort(key=lambda x: (x["success_rate"], x["record"]["execution_count"]), reverse=True)
        
        # 1. 高成功率的operators（可以优先考虑）
        high_success = [r for r in sorted_records if r["success_rate"] > 0.7]
        if high_success:
            summary_lines.append("## Reliable Operations (high success rate):")
            for item in high_success[:3]:
                summary_lines.append(
                    f"  ✓ {item['operator']}: {item['success_rate']:.0%} success "
                    f"({item['record']['success_count']}/{item['record']['execution_count']} executions)"
                )
        
        # 2. 常见失败和建议（需要特别注意）
        failed_ops = [r for r in sorted_records if r["record"]["failure_count"] > 0 and r["record"].get("suggestions")]
        if failed_ops:
            summary_lines.append("\n## Common Failure Patterns (avoid or add preprocessing):")
            for item in failed_ops[:max_entries]:
                operator = item["operator"]
                suggestions = item["record"].get("suggestions", [])
                failure_count = item["record"]["failure_count"]
                
                if suggestions:
                    suggestions_str = ", ".join(suggestions[:2])
                    summary_lines.append(
                        f"  ⚠️  {operator}: failed {failure_count} times"
                    )
                    summary_lines.append(f"      → Suggestion: {suggestions_str}")
        
        return "\n".join(summary_lines) if summary_lines else ""
    
    def get_code_generation_hints(
        self,
        operator_name: str,
        current_context: str,
        max_examples: int = 2
    ) -> Dict[str, Any]:
        """
        获取代码生成的提示信息，包括成功案例和失败模式。
        
        这个方法在SMG生成代码时被调用，帮助LLM：
        1. 借鉴历史上成功的代码写法
        2. 避免历史上常见的错误模式
        
        Args:
            operator_name: 要生成代码的operator
            current_context: 当前的table signature
            max_examples: 最多返回多少个示例
        
        Returns:
            {
                "success_examples": [...],
                "failure_patterns": [...],
                "suggestions": [...]
            }
        """
        hints = {
            "success_examples": [],
            "failure_patterns": [],
            "suggestions": []
        }
        
        # 查找该operator的所有历史记录
        for node in self.memory:
            if node.operator_name != operator_name:
                continue
            
            # 检查context相似度
            if node.state_before:
                node_context = self._get_table_signature_from_state(node.state_before)
                if not self._is_context_similar(current_context, node_context):
                    continue
            
            # 收集成功案例
            if node.success and len(hints["success_examples"]) < max_examples:
                hints["success_examples"].append({
                    "code": node.code[:300],  # 限制长度
                    "context": node_context if node.state_before else "unknown",
                    "explanation": node.reward_vector.explanation[:150] if node.reward_vector else ""
                })
            
            # 收集失败模式
            elif not node.success and len(hints["failure_patterns"]) < max_examples:
                hints["failure_patterns"].append({
                    "error": node.error_message[:200],
                    "code_attempt": node.code[:200],
                    "explanation": node.reward_vector.explanation[:150] if node.reward_vector else "",
                    "error_severity": node.reward_vector.error_severity if node.reward_vector else 0
                })
        
        # 从persistent memory获取建议
        context_key = f"{operator_name}+{current_context}"
        if context_key in self.persistent_memory:
            hints["suggestions"] = self.persistent_memory[context_key].get("suggestions", [])
        
        return hints
    
    def _get_table_signature_from_state(self, state) -> str:
        """从TableState生成signature"""
        if not state or not state.shape:
            return "unknown"
        
        # 统计类型
        type_counts = {}
        for col_type in state.column_types.values():
            if "int" in col_type.lower():
                type_name = "int"
            elif "float" in col_type.lower():
                type_name = "float"
            elif "object" in col_type.lower() or "str" in col_type.lower():
                type_name = "str"
            elif "datetime" in col_type.lower():
                type_name = "datetime"
            else:
                type_name = "other"
            
            type_counts[type_name] = type_counts.get(type_name, 0) + 1
        
        types_str = "_".join([f"{count}{tname}" for tname, count in sorted(type_counts.items())])
        return f"shape{state.shape}_types({types_str})"
    
    def _is_context_similar(self, context1: str, context2: str) -> bool:
        """
        简单的context相似度判断。
        主要比较列数和类型分布。
        """
        if context1 == "unknown" or context2 == "unknown":
            return False
        
        # 提取shape和types
        import re
        
        def extract_features(ctx):
            shape_match = re.search(r'shape\((\d+),(\d+)\)', ctx)
            if not shape_match:
                return (0, set())
            
            cols = int(shape_match.group(2))
            types = set(re.findall(r'\d+(\w+)', ctx))
            return (cols, types)
        
        f1 = extract_features(context1)
        f2 = extract_features(context2)
        
        # 列数相同，类型集合相似（至少50%重叠）
        if f1[0] != f2[0]:
            return False
        
        if not f1[1] or not f2[1]:
            return True  # 如果类型信息缺失，只要列数相同就认为相似
        
        overlap = len(f1[1] & f2[1])
        total = len(f1[1] | f2[1])
        
        return overlap / total >= 0.5 if total > 0 else False


def test_smg_module():
    """Test SMG module with mock components"""
    import pandas as pd
    
    # Mock LLM
    class MockLLM:
        def call_api(self, prompt):
            if "GROUP_BY" in prompt:
                return '''```python
df = df.groupby('department')['salary'].mean().reset_index()
df.columns = ['department', 'avg_salary']
```'''
            else:
                return "pass"
    
    # Mock Reward Evaluator
    class MockRewardEvaluator:
        def evaluate(self, **kwargs):
            from src.core.dtr_structures import RewardVector
            rv = RewardVector(
                execution_success=1.0 if kwargs.get("execution_success") else 0.0,
                query_satisfaction=0.8,
                code_reasonableness=0.9,
                efficiency=0.7,
                error_severity=0.0,
                explanation="Mock evaluation"
            )
            rv.compute_total()
            return rv
    
    # Create test data
    df = pd.DataFrame({
        'department': ['Sales', 'Sales', 'IT', 'IT', 'HR'],
        'employee': ['Alice', 'Bob', 'Charlie', 'David', 'Eve'],
        'salary': [50000, 55000, 60000, 65000, 45000]
    })
    
    # Create test operators and path
    from src.modules.ado_module import OPERATOR_BY_NAME
    
    operators = [
        OPERATOR_BY_NAME["GROUP_BY"],
        OPERATOR_BY_NAME["AGGREGATE"]
    ]
    
    from src.core.dtr_structures import ExecutionPath
    path = ExecutionPath(
        operators=["GROUP_BY", "AGGREGATE"],
        estimated_reward=0.8,
        path_id="PATH_A",
        reasoning="Test path"
    )
    
    # Initialize SMG
    llm = MockLLM()
    reward_eval = MockRewardEvaluator()
    smg = SMGModule(llm, reward_eval)
    
    # Execute
    print("Executing path...")
    results = smg.execute_paths(
        paths=[path],
        operator_pool=operators,
        dataframe=df,
        user_query="What is the average salary by department?",
        table_metadata={"column_names": list(df.columns)}
    )
    
    print(f"\n{'='*70}")
    print("Results:")
    print(f"  Best path: {results['best_path']}")
    print(f"  Best reward: {results['best_reward']:.3f}")
    print(f"  Final DataFrame shape: {results['best_df'].shape if results['best_df'] is not None else 'None'}")
    
    print(f"\nMemory Summary:")
    summary = smg.get_memory_summary()
    for key, value in summary.items():
        print(f"  {key}: {value}")
    
    return results, smg


if __name__ == "__main__":
    test_smg_module()

