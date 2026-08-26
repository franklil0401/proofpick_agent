"""
Reward Evaluator Module - LLM-based execution result evaluation
支持单个评估和批量评估
"""

import re
import json
from typing import Dict, List, Any, Optional
import pandas as pd

from src.core.dtr_structures import RewardVector


class RewardEvaluator:
    """LLM-based reward evaluator with batch support"""
    
    def __init__(self, llm_client):
        self.llm_client = llm_client
    
    def evaluate(
        self,
        code: str,
        operator_name: str,
        user_query: str,
        original_query: str,
        success: bool,
        error: Optional[str],
        before_df: pd.DataFrame,
        after_df: Optional[pd.DataFrame],
        execution_time: float
    ) -> RewardVector:
        """
        单个操作评估
        """
        
        # 直接评估，不通过evaluate_batch（避免递归）
        return self._evaluate_single(
            code=code,
            operator_name=operator_name,
            user_query=user_query,
            original_query=original_query,
            success=success,
            error=error,
            before_df=before_df,
            after_df=after_df,
            execution_time=execution_time
        )
    
    def evaluate_batch(
        self,
        operations: List[Dict[str, Any]],
        batch_size: int = 16  # 真正的批量评估：一次评估多个operations
    ) -> List[RewardVector]:
        """
        批量评估多个操作（分批调用LLM）
        
        策略：使用真正的批量评估加速
        - batch_size=16: 一次评估16个operations（快速）
        - batch_size=1: 逐个评估（最可靠，但慢）
        
        Args:
            operations: List of dicts with keys:
                - code, operator_name, user_query, original_query
                - success, error, before_df, after_df, execution_time
            batch_size: 每批评估的operations数量
        
        Returns:
            List of RewardVector objects
        """
        
        if not operations:
            return []
        
        all_rewards = []
        
        # 分批处理
        for i in range(0, len(operations), batch_size):
            batch = operations[i:i+batch_size]
            
            if batch_size == 1:
                # 单个评估
                op = batch[0]
                reward = self._evaluate_single(
                    code=op['code'],
                    operator_name=op['operator_name'],
                    user_query=op['user_query'],
                    original_query=op['original_query'],
                    success=op['success'],
                    error=op.get('error'),
                    before_df=op['before_df'],
                    after_df=op.get('after_df'),
                    execution_time=op['execution_time']
                )
                all_rewards.append(reward)
            else:
                # 批量评估（尝试，可能失败）
                try:
                    prompt = self._build_batch_evaluation_prompt(batch)
                    estimated_tokens = len(batch) * 200 + 2000
                    max_tokens = max(4000, min(estimated_tokens, 16000))
                    
                    response = self.llm_client.call_api(prompt, max_tokens=max_tokens)
                    rewards = self._parse_batch_response(response, len(batch), batch)  # 传入batch用于fallback
                    all_rewards.extend(rewards)
                except Exception as e:
                    print(f"⚠️  Batch evaluation failed for batch {i//batch_size}: {e}")
                    # Fallback：基于success的启发式评分
                    all_rewards.extend([self._default_reward(op['success']) for op in batch])
        
        return all_rewards
    
    def _evaluate_single(
        self,
        code: str,
        operator_name: str,
        user_query: str,
        original_query: str,
        success: bool,
        error: Optional[str],
        before_df: pd.DataFrame,
        after_df: Optional[pd.DataFrame],
        execution_time: float
    ) -> RewardVector:
        """内部单个评估方法（避免递归）"""
        
        # 构建prompt
        exec_status = "✅ SUCCESS" if success else f"❌ FAILED: {error}"
        
        before_info = f"Before: {before_df.shape}" if before_df is not None else "Before: N/A"
        after_info = f"After: {after_df.shape}" if after_df is not None and success else "After: N/A"
        
        prompt = f"""You are an expert evaluator assessing a data operation.

# Context
Original Query: {original_query}
Current Operation: {operator_name}
Operation Goal: {user_query}

# Code
```python
{code[:500]}
```

# Execution
Status: {exec_status}
DataFrame: {before_info} → {after_info}
Time: {execution_time:.3f}s

# Evaluation
Rate on these dimensions (0/0.5/1 or 0/1):

1. Execution Success (0/1): {1 if success else 0}
2. Query Satisfaction (0/0.5/1): Does it address the goal?
3. Code Reasonableness (0/0.5/1): Is the code appropriate?
4. Efficiency (0/1): Is it efficient?
5. Error Severity (0/0.5/1, if failed): How severe?

Output JSON only:
{{
  "execution_success": {1 if success else 0},
  "query_satisfaction": 0/0.5/1,
  "code_reasonableness": 0/0.5/1,
  "efficiency": 0/1,
  "error_severity": 0/0.5/1,
  "comments": "brief"
}}
"""
        
        try:
            response = self.llm_client.call_api(prompt)
            
            # 解析JSON
            import json
            import re
            
            json_match = re.search(r'\{[^{}]*"execution_success"[^{}]*\}', response, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(0))
                return RewardVector(
                    execution_success=float(result.get('execution_success', 0)),
                    query_satisfaction=float(result.get('query_satisfaction', 0)),
                    code_reasonableness=float(result.get('code_reasonableness', 0.5)),
                    efficiency=float(result.get('efficiency', 1)),
                    error_severity=float(result.get('error_severity', 0))
                )
        except:
            pass
        
        # Fallback
        return self._default_reward(success)
    
    def _build_batch_evaluation_prompt(self, operations: List[Dict]) -> str:
        """构建批量评估prompt"""
        
        # 总体上下文
        if operations:
            original_query = operations[0]['original_query']
        else:
            original_query = "Unknown query"
        
        prompt_parts = [
            f"""You are an expert evaluator assessing the quality of a sequence of data operations.

# Original User Query
{original_query}

# Operations Executed (in sequence)
"""
        ]
        
        # 添加每个操作的信息
        for idx, op in enumerate(operations, 1):
            exec_status = "✅ SUCCESS" if op['success'] else f"❌ FAILED: {op.get('error', 'Unknown error')}"
            
            # DataFrame信息
            before_info = f"Before: {op['before_df'].shape}" if op.get('before_df') is not None else "Before: N/A"
            after_info = f"After: {op['after_df'].shape}" if op.get('after_df') is not None and op['success'] else "After: N/A"
            
            prompt_parts.append(f"""
## Operation {idx}: {op['operator_name']}
**Goal**: {op.get('user_query', 'N/A')}
**Status**: {exec_status}
**DataFrame**: {before_info} → {after_info}
**Time**: {op.get('execution_time', 0):.3f}s

**Code**:
```python
{op['code'][:300]}{'...' if len(op['code']) > 300 else ''}
```
""")
        
        # 评估标准
        prompt_parts.append("""
---

# Evaluation Task

For EACH operation above, evaluate from these perspectives:

1. **Execution Success** (0/1)
   - 1: Code ran without errors
   - 0: Code failed

2. **Query Satisfaction** (0/0.5/1)
   - 1: Fully addresses the operation's goal
   - 0.5: Partially addresses
   - 0: Does not address

3. **Code Reasonableness** (0/0.5/1)
   - 1: Clean, correct, well-structured
   - 0.5: Works but has minor issues
   - 0: Poor quality or incorrect approach

4. **Efficiency** (0/1)
   - 1: Efficient implementation
   - 0: Obviously inefficient (only major issues count)

5. **Error Severity** (only if failed) (0/0.5/1)
   - 0: Error is easily recoverable (e.g., missing column check)
   - 0.5: Moderate issue (e.g., data type mismatch)
   - 1: Fundamental flaw in approach

---

# Output Format

Return a JSON array with one object per operation.

**CRITICAL**: You MUST output a JSON ARRAY starting with [ and ending with ], not individual objects!

Example format:
```json
[
  {{
    "operation": 1,
    "execution_success": 1,
    "query_satisfaction": 0.5,
    "code_reasonableness": 1,
    "efficiency": 1,
    "error_severity": 0,
    "comments": "brief explanation"
  }},
  {{
    "operation": 2,
    "execution_success": 1,
    "query_satisfaction": 1,
    "code_reasonableness": 0.5,
    "efficiency": 1,
    "error_severity": 0,
    "comments": "brief explanation"
  }}
]
```

**REQUIREMENTS**: 
- Start with [ and end with ]
- Include exactly {len(operations)} objects
- Each object must have "operation" field matching 1, 2, 3, ...
- Output ONLY the JSON array, no explanatory text before or after

Now output the JSON array for all {len(operations)} operations:
""")
        
        return "".join(prompt_parts)
    
    def _parse_batch_response(self, response: str, expected_count: int, operations: List[Dict] = None) -> List[RewardVector]:
        """解析批量评估响应（支持数组或多个独立对象）
        
        Args:
            response: LLM返回的响应
            expected_count: 期望的结果数量
            operations: 原始operations列表，用于fallback时获取success状态
        """
        
        # 方法1: 尝试提取JSON数组
        json_match = re.search(r'```json\s*(\[.*?\])\s*```', response, re.DOTALL)
        if not json_match:
            json_match = re.search(r'```\s*(\[.*?\])\s*```', response, re.DOTALL)
        if not json_match:
            json_match = re.search(r'(\[\s*\{.*?\}\s*\])', response, re.DOTALL)
        
        if json_match:
            json_str = json_match.group(1) if json_match.lastindex else json_match.group(0)
            try:
                results = json.loads(json_str)
                if isinstance(results, list):
                    return self._convert_to_reward_vectors(results, expected_count, operations)
            except:
                pass
        
        # 方法2: LLM返回了多个独立的JSON对象（不是数组）
        # 提取所有 {...} 对象
        print(f"⚠️  No JSON array found, trying to extract individual objects...")
        print(f"Response length: {len(response)} chars")
        
        try:
            # 找到所有JSON对象（支持嵌套）
            objects = []
            # 使用更宽松的匹配：找到包含"operation"的完整对象
            brace_count = 0
            current_obj = ""
            in_object = False
            
            for char in response:
                if char == '{':
                    if brace_count == 0:
                        in_object = True
                        current_obj = ""
                    brace_count += 1
                    current_obj += char
                elif char == '}':
                    brace_count -= 1
                    current_obj += char
                    if brace_count == 0 and in_object:
                        # 尝试解析
                        if '"operation"' in current_obj:
                            try:
                                obj = json.loads(current_obj)
                                objects.append(obj)
                            except:
                                pass
                        in_object = False
                elif in_object:
                    current_obj += char
            
            if objects:
                print(f"✓ Extracted {len(objects)} individual JSON objects")
                results = objects
            else:
                print(f"⚠️  Could not parse any JSON objects, using heuristic fallback")
                # Fallback：使用启发式评分（基于success状态）
                if operations:
                    return [self._default_reward(op['success']) for op in operations]
                else:
                    return [self._default_reward(True) for _ in range(expected_count)]
        except Exception as e:
            print(f"⚠️  Parsing failed: {e}, using heuristic fallback")
            if operations:
                return [self._default_reward(op['success']) for op in operations]
            else:
                return [self._default_reward(True) for _ in range(expected_count)]
        
        return self._convert_to_reward_vectors(results, expected_count, operations)
    
    def _convert_to_reward_vectors(self, results: List[Dict], expected_count: int, operations: List[Dict] = None) -> List[RewardVector]:
        """将JSON结果转换为RewardVector列表
        
        Args:
            results: 解析出的JSON结果列表
            expected_count: 期望的结果数量
            operations: 原始operations列表，用于fallback时获取success状态
        """
        
        try:
            results = results
            
            if not isinstance(results, list):
                print(f"⚠️  Response is not a list")
                if operations:
                    return [self._default_reward(op['success']) for op in operations]
                else:
                    return [RewardVector() for _ in range(expected_count)]
            
            # 转换为RewardVector
            rewards = []
            for i in range(expected_count):
                if i < len(results):
                    result = results[i]
                    rewards.append(RewardVector(
                        execution_success=float(result.get('execution_success', 0)),
                        query_satisfaction=float(result.get('query_satisfaction', 0)),
                        code_reasonableness=float(result.get('code_reasonableness', 0.5)),
                        efficiency=float(result.get('efficiency', 1)),
                        error_severity=float(result.get('error_severity', 0))
                    ))
                else:
                    # 缺少的条目用启发式值（基于success状态）
                    if operations and i < len(operations):
                        rewards.append(self._default_reward(operations[i]['success']))
                    else:
                        rewards.append(RewardVector())
            
            return rewards
            
        except json.JSONDecodeError as e:
            print(f"⚠️  JSON parsing failed: {e}")
            if operations:
                return [self._default_reward(op['success']) for op in operations]
            else:
                return [RewardVector() for _ in range(expected_count)]
    
    def _default_reward(self, success: bool) -> RewardVector:
        """默认reward（LLM失败时）"""
        
        if success:
            return RewardVector(
                execution_success=1.0,
                query_satisfaction=0.5,
                code_reasonableness=0.5,
                efficiency=1.0,
                error_severity=0.0
            )
        else:
            return RewardVector(
                execution_success=0.0,
                query_satisfaction=0.0,
                code_reasonableness=0.5,
                efficiency=1.0,
                error_severity=0.5
            )
