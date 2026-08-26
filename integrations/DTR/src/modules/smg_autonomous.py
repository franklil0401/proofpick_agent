"""
SMG Autonomous Module - 自主循环代码生成

核心改进：
1. 参考ADO提取的operator序列（作为指导）
2. 使用LLM自主循环，让LLM自己决定何时[THINK]/[CODE]/[Final Answer]
3. 最大10轮迭代，超时强制结束
4. 充分利用LLM的推理和规划能力
"""

import time
import re
import json
from typing import List, Dict, Any, Optional, Tuple
import pandas as pd
from datetime import datetime
import sys
from pathlib import Path
from io import StringIO

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
from src.core.dtr_structures import (
    Operator, ExecutionPath, TableState, SMGNode, RewardVector
)
from src.modules.multi_sheet_loader import MultiSheetContext
from src.modules.sheet_state_manager import SheetStateManager


class SMGAutonomousModule:
    """
    自主循环SMG模块
    
    核心思想：
    - ADO提供operator序列作为参考（而非强制执行）
    - LLM自主决策每一步：思考、写代码、或输出答案
    - 每次可以输出[THINK]/[CODE]/[Final Answer]标识
    - 最多10轮迭代
    """
    
    def __init__(self, llm_client, event_callback, reward_evaluator):
        self.llm_client = llm_client
        self.reward_evaluator = reward_evaluator
        self.event_callback = event_callback  # 添加事件回调
        self.memory: List[SMGNode] = []
        self.persistent_memory: Dict[str, List[SMGNode]] = {}
    
    def _emit_event(self, name: str, event_data: Dict[str, Any]):
        """发送事件到回调函数"""
        if self.event_callback:
            try:
                self.event_callback(name, event_data)
            except Exception as e:
                logger.warning(f"Failed to emit event: {e}")
    
    def execute_with_autonomous_loop(
        self,
        operator_sequence: List[str],  # ADO提取的operator序列(作为参考)
        operator_pool: List[Operator],  # 完整的operator池
        sheet_context: MultiSheetContext,  # 多sheet上下文
        user_query: str,
        table_metadata: Dict[str, Any],
        schema_result=None,
        max_iterations: int = 10
    ) -> Dict[str, Any]:
        """
        自主循环执行（多sheet版本）
        
        流程：
        1. 构建初始context（包含所有sheet信息）
        2. 进入自主循环（最多max_iterations轮）
        3. 每轮LLM可以：
           - [THINK]: 分析当前状态，规划下一步
           - [CODE]: 生成并执行代码（可指定sheet_name）
           - [Final Answer]: 输出最终答案，结束
        4. 达到上限后强制结束
        
        Args:
            operator_sequence: ADO提取的operator名称列表(作为参考指导)
            operator_pool: 完整的operator定义池
            sheet_context: 多sheet上下文
            user_query: 用户问题
            table_metadata: 表格元数据
            schema_result: Schema信息（可选）
            max_iterations: 最大迭代次数
        
        Returns:
            Dict with:
                - final_answer: 自然语言答案
                - execution_trace: 执行轨迹
                - memory_nodes: SMG节点
                - iterations_used: 实际使用的迭代次数
                - sheet_states: 最终的sheet状态
        """
        
        plan_str = "\n\n"
        plan_str += f"🔄 AUTONOMOUS LOOP EXECUTION (max {max_iterations} iterations)\n"
        plan_str += f"📋 Total Sheets: {sheet_context.total_sheets}\n"
        plan_str += f"   Sheets: {', '.join(sheet_context.get_sheet_names())}\n"
        plan_str += f"   Default: {sheet_context.default_sheet}\n"

        self._emit_event(
            name="excel_agent.plan.delta",
            event_data={
                "content": plan_str
            }
        )

        self._emit_event(
            name="excel_agent.plan.done",
            event_data={
                "content": "<plan_done>"
            }
        )
        
        # 构建operator信息字典
        operator_map = {op.name: op for op in operator_pool}
        
        # 创建Sheet状态管理器
        sheet_manager = SheetStateManager(sheet_context)
        
        # 构建初始prompt
        initial_prompt = self._build_initial_prompt(
            user_query=user_query,
            sheet_context=sheet_context,
            operator_sequence=operator_sequence,
            operator_map=operator_map,
            table_metadata=table_metadata,
            schema_result=schema_result
        )
        
        # 对话历史
        conversation_history = [initial_prompt]
        
        # 执行状态
        execution_trace = []
        code_executions = []  # 记录所有代码执行
        
        # 自主循环
        for iteration in range(max_iterations):

            self._emit_event(
                name="excel_agent.task.start",
                event_data={
                    "type": "reasoning",
                    "operation": f"Iteration {iteration + 1}/{max_iterations}",
                    "content": "<reasoning_start>"
                }
            )
            
            # 调用LLM
            current_input = self._format_conversation(conversation_history)
            try:
                response = self.llm_client.call_api(current_input, max_tokens=3072)
            except Exception as e:
                print(f"❌ LLM call failed: {e}")
                break
            
            # 记录response
            conversation_history.append(f"\n## Assistant Response (Round {iteration + 1})\n{response}")
            
            # 解析response，检测标识
            action, content = self._parse_response_action(response)
            
            print(f"🎯 Detected action: {action}")
            
            if action == "FINAL_ANSWER":
                # 找到最终答案，结束循环
                final_answer = self._extract_final_answer(response)
                print(f"✅ Final answer reached at iteration {iteration + 1}")
                print(f"   Answer: {final_answer[:100]}...")

                self._emit_event(
                    name="excel_agent.task.done",
                    event_data={
                        "type": "final answer",
                        "operation": f"[{action}]",
                        "content": "Finished",
                        "done": True
                    }
                )
                
                return {
                    "final_answer": final_answer,
                    "execution_trace": execution_trace,
                    "memory_nodes": self.memory,
                    "iterations_used": iteration + 1,
                    "code_executions": code_executions,
                    "sheet_states": sheet_context.sheet_states,
                    "success": True
                }
            
            elif action == "CODE":
                # 提取并执行代码
                code = self._extract_code_block(content)
                
                if not code or code.strip() == "pass":
                    print(f"⚠️  No valid code extracted, prompting LLM...")
                    feedback = "No code was extracted. Please provide valid Python code in [CODE] block."
                    conversation_history.append(f"\n## System Feedback\n{feedback}")
                    continue
                
                print(f"🔧 Executing code...")
                print(f"   Code preview: {code[:100]}...")

                self._emit_event(
                    name="excel_agent.task.delta",
                    event_data={
                        "type": "code_generation",
                        "operation": f"[{action}]",
                        "content": f"{code}",
                        "mode": "code",
                        "clean": True
                    }
                )
                
                # 执行代码（多sheet版本）
                start_time = time.time()
                exec_result = self._execute_code_safe(code, sheet_manager, iteration + 1)
                execution_time = time.time() - start_time
                
                success = exec_result["success"]
                error_msg = exec_result.get("error", "")
                updated_sheets = exec_result.get("updated_sheets", [])
                modified_info = exec_result.get("modified_sheets_info", [])
                
                # 记录执行
                code_executions.append({
                    "iteration": iteration + 1,
                    "code": code,
                    "success": success,
                    "error": error_msg,
                    "updated_sheets": updated_sheets,
                    "execution_time": execution_time
                })
                
                if success:
                    # 成功执行
                    sheets_summary = ", ".join([f"'{s}'" for s in updated_sheets]) if updated_sheets else "No sheets modified"
                    print(f"   ✅ Execution succeeded")
                    print(f"   Updated sheets: {sheets_summary}")
                    
                    # 构建成功反馈
                    feedback = self._build_success_feedback(exec_result, sheet_manager)
                    conversation_history.append(feedback)
                    
                    # 添加到execution trace
                    execution_trace.append({
                        "iteration": iteration + 1,
                        "action": "CODE_EXECUTION",
                        "code": code,
                        "success": True,
                        "updated_sheets": updated_sheets,
                        "modified_info": modified_info
                    })

                    self._emit_event(
                        name="excel_agent.task.done",
                        event_data={
                            "type": "code_execution",
                            "operation": f"[{action}] | ✅ Updated: {sheets_summary}",
                            "content": f"✅ Execution Success: {sheets_summary}"
                        }
                    )

                    task_type = "code_execution"
                    operation = f"[{action}] | ✅ Execution Success"
                    
                else:
                    # 执行失败
                    print(f"   ❌ Execution failed: {error_msg[:100]}")
                    
                    # 构建错误反馈
                    feedback = self._build_error_feedback(exec_result, sheet_manager)
                    conversation_history.append(feedback)
                    
                    # 添加到execution trace
                    execution_trace.append({
                        "iteration": iteration + 1,
                        "action": "CODE_EXECUTION",
                        "code": code,
                        "success": False,
                        "error": error_msg
                    })

                    self._emit_event(
                        name="excel_agent.task.done",
                        event_data={
                            "type": "code_execution",
                            "operation": f"[{action}] | ❌ Execution Failed",
                            "content": f"❌ Execution Failed: {error_msg}"
                        }
                    )

                    task_type = "code_execution"
                    operation = f"[{action}] | ❌ Execution Failed"
            
            elif action == "THINK":
                # LLM在思考，记录并继续
                print(f"💭 LLM is thinking/reflecting...")
                thought = self._extract_think_content(content)
                print(f"   Thought: {thought[:150]}...")

                self._emit_event(
                    name="excel_agent.task.delta",
                    event_data={
                        "type": "reflection",
                        "operation": f"[{action}]",
                        "content": f"{thought}",
                        "clean": True
                    }
                )

                task_type = "reflection"
                operation = f"[{action}]"
                
                # 记录思考
                execution_trace.append({
                    "iteration": iteration + 1,
                    "action": "THINK",
                    "content": thought
                })
                
                # 提示继续
                continuation = """
Good thinking! Based on your analysis, what's your next step?

You can:
- Use **[CODE]** to write and execute code
- Use **[THINK]** to continue analyzing
- Use **[Final Answer]** if you have the complete answer

What would you like to do?
"""
                conversation_history.append(continuation)
            
            else:
                # 没有明确标识，提醒使用标识
                print(f"⚠️  No clear action tag detected, reminding LLM...")

                self._emit_event(
                    name="excel_agent.task.delta",
                    event_data={
                        "type": "reflection",
                        "operation": f"[{action}]",
                        "content": f"⚠️  No clear action tag detected, reminding LLM...",
                        "clean": True
                    }
                )

                task_type = "reflection"
                operation = f"[{action}]"
                
                reminder = """
Please use one of these tags to indicate your action:

- **[THINK]** - Analyze the current situation and plan next steps
- **[CODE]** - Write Python/Pandas code to process data
- **[Final Answer]** - Provide your final answer to the question

What would you like to do next?
"""
                conversation_history.append(reminder)
            
            if "code" in task_type:
                pass
            else:
                self._emit_event(
                    name="excel_agent.task.done",
                    event_data={
                        "type": task_type,
                        "operation": operation,
                        "content": "<task_done>"
                    }
                )
        
        # 达到最大迭代次数，强制结束
        print(f"\n{'='*60}")
        print(f"⚠️  Reached maximum iterations ({max_iterations})")
        print(f"{'='*60}")
        print(f"Forcing final answer extraction...")

        self._emit_event(
            name="excel_agent.task.start",
            event_data={
                "type": "reflection",
                "operation": f"[FORCE FINAL ANSWER]",
                "content": f"⚠️  Reached maximum iterations ({max_iterations})\nForcing final answer extraction...",
                "clean": True
            }
        )
        
        final_answer = self._force_extract_answer(
            conversation_history=conversation_history,
            sheet_manager=sheet_manager,
            user_query=user_query,
            table_metadata=table_metadata
        )

        self._emit_event(
            name="excel_agent.task.delta",
            event_data={
                "type": "reflection",
                "operation": f"[FORCE FINAL ANSWER]",
                "content": f"{final_answer}",
                "clean": True
            }
        )
        
        return {
            "final_answer": final_answer,
            "execution_trace": execution_trace,
            "memory_nodes": self.memory,
            "iterations_used": max_iterations,
            "code_executions": code_executions,
            "sheet_states": sheet_context.sheet_states,
            "success": False,  # 超时被迫结束
            "reason": "max_iterations_reached"
        }
    
    def _build_initial_prompt(
        self,
        user_query: str,
        sheet_context: MultiSheetContext,
        operator_sequence: List[str],
        operator_map: Dict[str, Operator],
        table_metadata: Dict[str, Any],
        schema_result=None
    ) -> str:
        """构建初始prompt（多sheet版本）"""
        
        # 加载器用于生成sheets概览
        from src.modules.multi_sheet_loader import MultiSheetLoader
        loader = MultiSheetLoader()
        
        # 生成所有sheet的概览
        sheets_overview = loader.generate_sheets_overview(sheet_context, include_preview=True)
        
        # 生成sheet选择指南
        sheet_selection_guide = loader.generate_sheet_selection_guide()
        
        # Operator参考信息
        operator_reference = self._build_operator_reference(operator_sequence, operator_map)
        
        # Schema信息（如果有）
        schema_hint = ""
        if schema_result and schema_result.selected_col_headers:
            schema_hint = f"""
## 🎯 Schema Information (Relevant Headers)

**Relevant Columns** ({len(schema_result.selected_col_headers)}):
{', '.join(schema_result.selected_col_headers[:20])}

💡 These columns were identified as most relevant to the query.
"""
        
        # 表格元数据信息
        meta_hint = ""
        if table_metadata:
            total_sheets = table_metadata.get("total_sheets", 1)
            if total_sheets > 1:
                meta_hint = f"\n## 📋 Multi-Sheet Context\n"
                meta_hint += f"- Total Sheets: {total_sheets}\n"
                meta_hint += f"- Sheet Names: {', '.join(table_metadata.get('sheet_names', []))}\n"
                meta_hint += f"- Default Sheet: {table_metadata.get('default_sheet', 'N/A')}\n"
        
        prompt = f"""# Autonomous Code Generation Task (Multi-Sheet Support)

You are solving a tabular data question using an **autonomous iterative process** with **multi-sheet Excel support**.

## 🎯 Your Goal

Answer this question: **{user_query}**

{sheets_overview}

{sheet_selection_guide}
{schema_hint}
{meta_hint}

## 💡 Reference Operator Sequence (Optional)

The following operator sequence was suggested by our analysis module.
You can **follow** these steps or **deviate** based on your judgment.

{operator_reference}

⚠️ **Important**: This sequence is a REFERENCE, not a strict requirement.

## 🏷️ Action Tags You Can Use

At each iteration, indicate your action using one of these tags:

### 1. **[THINK]** or **[REFLECT]**
When you need to:
- Analyze the current situation and data structure
- Develop your analytical reasoning  
- Plan your approach or reflect on results
- Draw insights from data patterns

**Quality over brevity**: Take 5-8 sentences to think thoroughly when needed.

Example:
```
[THINK]
The question requires data from multiple sheets. Looking at the available sheets, 
Sheet1 contains the main data while Sheet2 has reference information. I should first 
process Sheet1 to extract the key metrics, then use Sheet2 to enrich the results. 
The analysis requires aggregation across categories and time periods.
```

### 2. **[CODE]** (Optional - use when truly needed)
Execute Python/Pandas code to process data across multiple sheets.

Example:
```
[CODE]
```python
# Access and modify any sheet through the sheets dictionary
sales_df = sheets['Sales Data']
products_df = sheets['Products']

# Filter and process
sales_filtered = sales_df[sales_df['Year'] > 2020]
merged = pd.merge(sales_filtered, products_df, on='ProductID')

# Update sheets - MUST assign DataFrame, not dict or other types
sheets['Sales Data'] = sales_filtered  # ✓ DataFrame
sheets['Merged Results'] = merged      # ✓ DataFrame

# WRONG examples (do NOT assign dict/list):
# sheets['Summary'] = dict(total=100)     # ✗ dict not allowed
# sheets['List'] = [1, 2, 3]              # ✗ list not allowed
```
```

**Critical code rules**:
- Use `sheets['SheetName']` to access and modify any sheet
- **CRITICAL**: Every value in `sheets` MUST be a pandas DataFrame (not dict, list, or other types)
- All sheets are available in the `sheets` dictionary
- You can modify multiple sheets in a single code block
- All modifications are persisted for future iterations
- New sheets can be created by assigning to `sheets['NewName']`
- **MUST use English variable names ONLY** (e.g., `sales_df`, `total_revenue`) - NO Chinese characters in variable names

### 3. **[Final Answer]**
Provide a **detailed, well-structured response**.

**CRITICAL - Your final answer MUST follow these quality standards**:
1. Use Markdown formatting (headers ##/###, lists, emphasis)
2. Present data in Markdown tables when appropriate
3. Include specific numerical results with proper context
4. Provide deep analysis and insights (not just numbers)
5. Give actionable, specific recommendations
6. For visualization questions: include complete Python code in ```python blocks

## ⚠️ OUTPUT FORMAT CONSTRAINTS

**CRITICAL**: Each iteration, you MUST output EXACTLY ONE action tag and its content.

**Rules**:
1. Start your response directly with one of: `[THINK]`, `[CODE]`, or `[Final Answer]`
2. Do NOT add any extra text before or after the action
3. Output ONLY the selected action

## 🚀 Start Your Analysis

You have up to 10 iterations. Think carefully and decide your approach.

**Available Actions**:
- **[THINK]**: Deep analytical reasoning (5-8 sentences for complex problems)
- **[CODE]**: Execute Python code with multi-sheet support via `sheets` dictionary
- **[Final Answer]**: Provide comprehensive, well-formatted final answer

**Multi-Sheet Workflow Tips**:
- Access any sheet via `sheets['SheetName']`
- Modify sheets by assigning back to `sheets['SheetName']`
- **CRITICAL**: `sheets['SheetName']` must ALWAYS be a pandas DataFrame - NO dict, list, or other types
- You can process multiple sheets in one code block
- Create new sheets by assigning to new keys in `sheets`
- All modifications persist across iterations
- **Variable Naming**: Use English names ONLY (e.g., `product_df`, `sales_total`, NOT `产品_df`, `销售总额`)

**Remember**: Your goal is to provide high-quality, comprehensive answers.

Begin now:
"""
        
        return prompt
    
    def _build_operator_reference(
        self,
        operator_sequence: List[str],
        operator_map: Dict[str, Operator]
    ) -> str:
        """构建operator参考信息"""
        
        lines = []
        lines.append("**Suggested Steps**:")
        
        for idx, op_name in enumerate(operator_sequence, 1):
            operator = operator_map.get(op_name)
            if operator:
                lines.append(f"\n{idx}. **{operator.name}**")
                lines.append(f"   Description: {operator.description}")
                lines.append(f"   Category: {operator.category.value}")
            else:
                lines.append(f"\n{idx}. **{op_name}** (details not available)")
        
        return "\n".join(lines)
    
    def _format_conversation(self, history: List[str]) -> str:
        """
        格式化对话历史
        为了控制prompt长度和加快生成，只保留最近的关键轮次
        """
        if len(history) <= 6:
            # 少于6条消息，全部保留
            return "\n\n".join(history)
        else:
            # 保留初始prompt + 最近5轮对话
            initial_prompt = history[0]
            recent_history = history[-5:]
            return "\n\n".join([initial_prompt] + recent_history)
    
    def _parse_response_action(self, response: str) -> Tuple[str, str]:
        """
        解析response，识别action
        
        Returns:
            (action_type, content)
            action_type: "THINK", "CODE", "FINAL_ANSWER", "UNKNOWN"
        """
        
        response_lower = response.lower()
        
        # 检测[Final Answer]
        if "[final answer]" in response_lower:
            return ("FINAL_ANSWER", response)
        
        # 检测[CODE]
        if "[code]" in response_lower:
            return ("CODE", response)
        
        # 检测[THINK]或[REFLECT]
        if "[think]" in response_lower or "[reflect]" in response_lower:
            return ("THINK", response)
        
        return ("UNKNOWN", response)
    
    def _extract_code_block(self, response: str) -> str:
        """从response中提取代码块"""
        
        # 方法1: 查找[CODE]标签后的```python代码块
        pattern = r'\[CODE\]\s*```(?:python)?\s*(.*?)```'
        matches = re.findall(pattern, response, re.DOTALL | re.IGNORECASE)
        
        if matches:
            return matches[0].strip()
        
        # 方法2: 查找任意```python代码块
        pattern2 = r'```(?:python)?\s*(.*?)```'
        matches2 = re.findall(pattern2, response, re.DOTALL)
        
        if matches2:
            # 如果有多个代码块，合并它们
            return '\n\n'.join(m.strip() for m in matches2)
        
        # # 方法3: 查找[CODE]后到下一个标签之间的内容
        # pattern3 = r'\[CODE\](.*?)(?:\[THINK\]|\[REFLECT\]|\[Final Answer\]|$)'
        # matches3 = re.findall(pattern3, response, re.DOTALL | re.IGNORECASE)
        
        # if matches3:
        #     code = matches3[0].strip()
        #     # 移除可能的markdown标记
        #     code = re.sub(r'^```(?:python)?\s*', '', code)
        #     code = re.sub(r'```\s*$', '', code)
        #     return code.strip()
        
        return ""
    
    def _extract_think_content(self, response: str) -> str:
        """提取[THINK]标签的内容"""
        
        pattern = r'\[THINK\](.*?)(?:\[CODE\]|\[Final Answer\]|$)'
        matches = re.findall(pattern, response, re.DOTALL | re.IGNORECASE)
        
        if matches:
            return matches[0].strip()
        
        pattern2 = r'\[REFLECT\](.*?)(?:\[CODE\]|\[Final Answer\]|$)'
        matches2 = re.findall(pattern2, response, re.DOTALL | re.IGNORECASE)
        
        if matches2:
            return matches2[0].strip()
        
        return response[:500]  # 返回前500字符作为fallback
    
    def _extract_final_answer(self, response: str) -> str:
        """提取[Final Answer]内容"""
        
        pattern = r'\[Final Answer\]:?\s*(.*?)(?:\n\n\[|$)'
        matches = re.findall(pattern, response, re.DOTALL | re.IGNORECASE)
        
        if matches:
            answer = matches[0].strip()
            # 如果答案很短，可能提取不完整
            if len(answer) < 50:
                parts = response.split("[Final Answer]", 1)
                if len(parts) > 1:
                    answer = parts[1].strip()
                    answer = re.sub(r'^:\s*', '', answer)
            
            return f"{answer}"
        
        # Fallback: 返回整个response
        return response
    
    def _execute_code_safe(self, code: str, sheet_manager: SheetStateManager, iteration: int = 0) -> Dict[str, Any]:
        """安全执行代码（多sheet版本）
        
        允许在一次执行中操作多个sheet。代码通过sheets字典访问和修改任意sheet。
        
        Args:
            code: Python代码
            sheet_manager: Sheet状态管理器
            iteration: 当前迭代轮次
            
        Returns:
            执行结果字典，包含所有被修改的sheet信息
        """
        
        import numpy as np
        
        if not code:
            return {"success": False, "error": "Empty code"}
        
        # 安全检查
        forbidden = ["exit(", "quit(", "sys.exit", "os.system", "subprocess", 
                     "__import__", "eval(", "exec(", "open("]
        for kw in forbidden:
            if kw in code:
                return {"success": False, "error": f"Forbidden keyword: {kw}"}
        
        # 1. 准备可修改的sheets字典
        # 为每个sheet创建一个副本，代码可以直接修改
        sheets_dict = {}
        for sheet_name in sheet_manager.get_sheet_names():
            try:
                sheets_dict[sheet_name] = sheet_manager.get_current_df(sheet_name).copy()
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Failed to load sheet '{sheet_name}': {e}"
                }
        
        # 2. 准备执行环境
        local_vars = {
            "sheets": sheets_dict,  # 可修改的sheets字典
            "pd": pd,
            "np": np
        }
        
        global_vars = {
            "pd": pd,
            "np": np,
            "__builtins__": __builtins__
        }
        
        # 3. 执行代码并捕获print输出
        try:
            captured_output = StringIO()
            old_stdout = sys.stdout
            
            try:
                sys.stdout = captured_output  # 重定向stdout
                exec(code, global_vars, local_vars)
            finally:
                sys.stdout = old_stdout  # 恢复stdout
            
            # 获取print输出
            print_output = captured_output.getvalue()
            print(f"Print output:\n{print_output}")
            
            # 4. 检查哪些sheet被修改了，并更新状态
            updated_sheets = []
            modified_sheets_info = []
            new_sheets = []  # 新创建的sheet
            
            result_sheets = local_vars.get("sheets", {})
            
            for sheet_name, result_df in result_sheets.items():
                # 自动转换dict为DataFrame
                if isinstance(result_df, dict):
                    try:
                        result_df = pd.DataFrame(result_df)
                        print(f"    ℹ️  Auto-converted dict to DataFrame for sheet '{sheet_name}'")
                    except Exception as e:
                        return {
                            "success": False,
                            "error": f"Sheet '{sheet_name}' is dict but cannot convert to DataFrame: {e}"
                        }
                
                # 确保是DataFrame
                if not isinstance(result_df, pd.DataFrame):
                    return {
                        "success": False,
                        "error": f"Sheet '{sheet_name}' must be DataFrame, got {type(result_df).__name__}"
                    }
                
                # 判断是新sheet还是修改已有sheet
                is_new_sheet = not sheet_manager.has_sheet(sheet_name)
                
                if is_new_sheet:
                    # 新创建的sheet
                    add_success = sheet_manager.add_new_sheet(
                        sheet_name,
                        result_df,
                        iteration,
                        operation_summary="Created by code execution"
                    )
                    
                    if not add_success:
                        return {
                            "success": False,
                            "error": f"Failed to add new sheet '{sheet_name}'"
                        }
                    
                    new_sheets.append(sheet_name)
                    updated_sheets.append(sheet_name)
                    modified_sheets_info.append({
                        "sheet": sheet_name,
                        "shape": result_df.shape,
                        "is_new": True
                    })
                    print(f"    ✨ Created new sheet '{sheet_name}': {result_df.shape}")
                    
                else:
                    # 检查是否被修改（通过shape或内容变化判断）
                    original_df = sheet_manager.get_current_df(sheet_name)
                    is_modified = (
                        result_df.shape != original_df.shape or 
                        not result_df.equals(original_df)
                    )
                    
                    if is_modified:
                        # 更新sheet状态
                        update_success = sheet_manager.update_sheet(
                            sheet_name,
                            result_df,
                            iteration,
                            operation_summary="Code execution"
                        )
                        
                        if not update_success:
                            return {
                                "success": False,
                                "error": f"Failed to update sheet state for '{sheet_name}'"
                            }
                        
                        updated_sheets.append(sheet_name)
                        modified_sheets_info.append({
                            "sheet": sheet_name,
                            "shape": result_df.shape,
                            "is_new": False
                        })
                        print(f"    ✅ Updated sheet '{sheet_name}': {result_df.shape}")
            
            if not updated_sheets:
                print(f"    ℹ️  No sheets were modified")
            
            return {
                "success": True,
                "updated_sheets": updated_sheets,
                "modified_sheets_info": modified_sheets_info,
                "new_sheets": new_sheets,
                "print_output": print_output.strip() if print_output.strip() else None,
                "error": None
            }
        
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def _build_success_feedback(self, exec_result: Dict, sheet_manager: SheetStateManager) -> str:
        """构建成功执行的反馈（多sheet版本）"""
        
        updated_sheets = exec_result.get("updated_sheets", [])
        modified_info = exec_result.get("modified_sheets_info", [])
        new_sheets = exec_result.get("new_sheets", [])
        print_output = exec_result.get("print_output")
        
        if not updated_sheets:
            feedback = """
## ✅ Code Execution Successful!

**Note**: No sheets were modified by this execution.

---

**Sheet States Summary**:
"""
        else:
            # 分类显示新创建和修改的sheet
            new_sheets_info = [info for info in modified_info if info.get("is_new", False)]
            modified_sheets_info = [info for info in modified_info if not info.get("is_new", False)]
            
            parts = []
            
            if new_sheets_info:
                new_summary = "\n".join([
                    f"- **✨ {info['sheet']}** (NEW): {info['shape'][0]} rows × {info['shape'][1]} columns"
                    for info in new_sheets_info
                ])
                parts.append(f"**New Sheets Created** ({len(new_sheets_info)}):\n{new_summary}")
            
            if modified_sheets_info:
                mod_summary = "\n".join([
                    f"- **{info['sheet']}**: {info['shape'][0]} rows × {info['shape'][1]} columns"
                    for info in modified_sheets_info
                ])
                parts.append(f"**Modified Sheets** ({len(modified_sheets_info)}):\n{mod_summary}")
            
            sheets_summary = "\n\n".join(parts)
            
            feedback = f"""
## ✅ Code Execution Successful!

{sheets_summary}

---

**All Sheet States**:
"""
        
        feedback += f"{sheet_manager.get_compact_summary()}\n\n"
        
        # 添加print输出（如果有）
        if print_output:
            feedback += f"""---

**Print Output**:
```
{print_output}
```

"""
        
        feedback += """---

**What's your next step?**
- Use **[THINK]** to deeply analyze these results and draw insights
- Use **[CODE]** to continue processing (modify any sheet via `sheets` dictionary)
- Use **[Final Answer]** if you can now provide a comprehensive, detailed answer
"""
        
        return feedback
    
    def _build_error_feedback(self, exec_result: Dict, sheet_manager: Optional[SheetStateManager] = None) -> str:
        """构建失败执行的反馈（多sheet版本）"""
        
        error_msg = exec_result.get("error", "Unknown error")
        
        feedback = f"""
## ❌ Code Execution Failed

**Error Message**:
```
{error_msg}
```

---
"""
        
        # 添加sheet状态信息（如果有）
        if sheet_manager:
            feedback += f"""
**Current Sheet States**:
{sheet_manager.get_compact_summary()}

---

"""
        
        feedback += """
**Please use [THINK] to:**
1. Analyze what went wrong
2. Understand the root cause
3. Plan how to fix it

Then use **[CODE]** to try again with corrected code.
"""
        
        return feedback
    
    def _force_extract_answer(
        self,
        conversation_history: List[str],
        sheet_manager: SheetStateManager,
        user_query: str,
        table_metadata: Dict[str, Any] = None
    ) -> str:
        """达到最大迭代次数，强制提取答案（多sheet版本）"""
        
        # 尝试从最后几轮中提取有用信息
        recent_history = "\n\n".join(conversation_history[-5:])
        
        # 获取所有sheet的状态摘要
        sheets_summary = sheet_manager.get_all_states_summary(include_unmodified=False)
        
        # 构建强制提取prompt
        force_prompt = f"""
You've reached the iteration limit. Please provide your **COMPREHENSIVE final answer NOW** based on all the work done.

## Original Question
{user_query}

## Current Sheet States
{sheets_summary}

## Recent History (last 5 interactions)
{recent_history[:3000]}

---

**CRITICAL: Provide a HIGH-QUALITY [Final Answer] that includes:**

1. **Specific numerical results**: Include all relevant statistics, calculations, and metrics
2. **Deep analysis**: Explain patterns, trends, and what the numbers mean
3. **Clear insights**: What are the key takeaways and implications?
4. **Actionable recommendations**: Specific, feasible suggestions (not vague advice)
5. **Professional formatting**: Use Markdown headers, tables, lists appropriately
6. **Visualization code**: If the question asks for charts, include complete Python code

**Your answer should demonstrate:**
- Thoroughness (comprehensive coverage of all aspects)
- Depth (insightful analysis, not just surface-level description)
- Clarity (well-organized, easy to understand)
- Utility (actionable and practical)

Use this format:
[Final Answer]
<your detailed, comprehensive answer here>
"""
        
        try:
            response = self.llm_client.call_api(force_prompt, max_tokens=4096)
            return self._extract_final_answer(response)
        except Exception as e:
            print(f"❌ Force extraction failed: {e}")
            # Fallback: 基于sheet状态生成简单答案
            default_sheet = sheet_manager.get_default_sheet()
            current_df = sheet_manager.get_current_df(default_sheet)
            
            if current_df.empty:
                return "[Final Answer]: No data available to answer the question."
            else:
                return f"[Final Answer]: Based on the processed data in sheet '{default_sheet}' (shape: {current_df.shape}), here are the results:\n{current_df.head(10).to_string()}"
    
    def get_memory_summary(self) -> Dict[str, Any]:
        """获取内存摘要"""
        if not self.memory:
            return {
                "total_nodes": 0,
                "success_rate": 0.0,
                "avg_reward": 0.0
            }
        
        success_count = sum(1 for node in self.memory if node.success)
        
        return {
            "total_nodes": len(self.memory),
            "success_count": success_count,
            "failure_count": len(self.memory) - success_count,
            "success_rate": success_count / len(self.memory) if self.memory else 0.0
        }
    
    def clear_memory(self):
        """清空内存"""
        self.memory = []
