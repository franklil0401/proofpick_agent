"""
DTR Framework - Integration Layer

Integrates ADO, MCTS, and SMG modules into a cohesive system.
Provides interface compatible with existing entry point (run_benchmark_v4.py).
"""

import sys
import os
from pathlib import Path
from typing import Dict, Any, Optional, List
import pandas as pd

# Add parent to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Import DTR modules
from src.core.dtr_structures import serialize_to_json, log_structure
from src.modules.ado_module import ADOModule
from src.modules.mcts_planner import MCTSPlanner
from src.modules.smg_module import SMGModule
from src.modules.reward_evaluator import RewardEvaluator


class DTRFramework:
    """
    Deep Tabular Research Framework
    
    End-to-end system that:
    1. Decomposes queries into operators (ADO)
    2. Plans execution paths (MCTS)
    3. Generates code, executes, and learns (SMG)
    """
    
    def __init__(self, llm_client, logger, enable_experience=True, num_paths=2, enable_multi_stage=False):
        """
        Args:
            llm_client: LLM client with call_api(prompt) -> str method
            logger: Logger instance
            enable_experience: 是否启用经验管理（保存和加载经验）
            num_paths: MCTS生成的path数量（1=快速，2=准确，3=最优）
            enable_multi_stage: 启用Multi-Stage代码生成（Understanding-Generation-Reflection）
        """
        self.llm_client = llm_client
        self.logger = logger
        self.enable_experience = enable_experience
        self.num_paths = num_paths
        self.enable_multi_stage = enable_multi_stage
        
        # Initialize experience manager
        if enable_experience:
            from utils.experience_manager import ExperienceManager
            self.experience_manager = ExperienceManager()
        else:
            self.experience_manager = None
        
        # Initialize modules
        self.logger.info("Initializing DTR Framework modules...")
        
        # Schema Linking模块（统一入口）
        from src.modules.schema_linking import SchemaLinkingModule
        self.schema_linker = SchemaLinkingModule(llm_client)
        self.logger.info("  ✓ Schema Linking Module initialized")
        
        self.ado = ADOModule(llm_client)
        self.logger.info("  ✓ ADO Module initialized")
        
        self.mcts = MCTSPlanner(
            exploration_weight=1.414,
            max_iterations=50,
            max_path_length=8
        )
        self.logger.info("  ✓ MCTS Planner initialized")
        
        self.reward_evaluator = RewardEvaluator(llm_client)
        self.logger.info("  ✓ Reward Evaluator initialized")
        
        self.smg = SMGModule(llm_client, self.reward_evaluator, enable_multi_stage=self.enable_multi_stage)
        if self.enable_multi_stage:
            self.logger.info("  ✓ SMG Module initialized (Multi-Stage ENABLED)")
        else:
            self.logger.info("  ✓ SMG Module initialized")
        
        # Answer generator
        from src.modules.answer_generator import AnswerGenerator
        self.answer_generator = AnswerGenerator(llm_client)
        self.logger.info("  ✓ Answer Generator initialized")
        
        self.logger.info("DTR Framework ready!")
    
    def process_query(
        self,
        user_query: str,
        dataframe: pd.DataFrame,
        table_metadata: Optional[Dict[str, Any]] = None,
        meta_graph: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Process a tabular query end-to-end.
        
        Args:
            user_query: Natural language question
            dataframe: Input pandas DataFrame
            table_metadata: Optional metadata dict
            meta_graph: Optional meta graph for schema linking
        
        Returns:
            Dict containing:
                - final_answer: Result DataFrame or answer
                - execution_trace: List of executed operations
                - memory_nodes: SMG memory nodes
                - best_path_id: ID of best execution path
                - schema_linking: Schema linking result
                - logs: Detailed logs
        """
        
        if table_metadata is None:
            table_metadata = self._extract_metadata(dataframe)
        
        # ==================== STEP 0: Schema Linking (新增统一入口) ====================
        schema_result = None
        if meta_graph:
            self.logger.info("="*70)
            self.logger.info("STEP 0: Schema Linking - Intelligent Header Selection")
            self.logger.info("="*70)
            
            try:
                schema_result = self.schema_linker.link_schema(
                    user_query, meta_graph
                )
                
                self.logger.info(f"✓ Schema Linking completed:")
                self.logger.info(f"  - Selected {len(schema_result.selected_row_headers)} row headers")
                self.logger.info(f"  - Selected {len(schema_result.selected_col_headers)} col headers")
                self.logger.info(f"  - Confidence: {schema_result.confidence:.2f}")
                
                if schema_result.selected_row_headers:
                    self.logger.info(f"  - Sample row headers: {schema_result.selected_row_headers[:3]}")
                if schema_result.selected_col_headers:
                    self.logger.info(f"  - Sample col headers: {schema_result.selected_col_headers[:3]}")
            except Exception as e:
                self.logger.warning(f"Schema Linking failed: {e}, continuing without it")
                schema_result = None
        
        logs = []
        
        # 记录schema信息（如果有）
        if schema_result:
            logs.append({
                "step": "Schema_Linking",
                "row_headers": schema_result.selected_row_headers,
                "col_headers": schema_result.selected_col_headers,
                "confidence": schema_result.confidence
            })
        
        # ==================== STEP 1: ADO - Operator Extraction ====================
        self.logger.info("="*70)
        self.logger.info("STEP 1: ADO - Operator Extraction (with schema + historical experience)")
        self.logger.info("="*70)
        
        # ⭐ 传入smg_module和schema_result，让ADO能利用历史经验和Schema信息
        ado_result = self.ado.extract_operators(
            user_query,
            table_metadata,
            smg_module=self.smg,  # 传入SMG以访问历史经验
            schema_result=schema_result  # 新增：传入Schema信息
        )
        
        self.logger.info(f"Extracted {len(ado_result.operators)} operators:")
        for op in ado_result.operators:
            self.logger.info(f"  - {op.name} (cost={op.estimated_cost})")
        
        logs.append({
            "step": "ADO",
            "operators": [op.name for op in ado_result.operators],
            "count": len(ado_result.operators)
        })
        
        if not ado_result.operators:
            self.logger.warning("No operators extracted, attempting retry...")
            # 触发retry机制
            retry_result = self._retry_with_replanning(
                user_query=user_query,
                dataframe=dataframe,
                table_metadata=table_metadata,
                previous_execution_trace=[],
                max_retries=1,
                retry_reason="no_operators"
            )
            
            if retry_result and retry_result.get("final_answer"):
                retry_answer = retry_result["final_answer"]
                # 检查retry是否成功（不是错误消息）
                if not self._is_error_message(retry_answer):
                    self.logger.info(f"✓ Retry successful after no operators! New answer: {retry_answer}")
                    return retry_result
            
            # Retry失败，使用直接LLM回答作为兜底
            self.logger.warning("Retry failed, using direct LLM fallback...")
            question_type = table_metadata.get("question_type", "") if table_metadata else ""
            sub_q_type = table_metadata.get("sub_q_type", "") if table_metadata else ""
            fallback_answer = self.answer_generator._generate_direct_llm_answer(
                user_query=user_query,
                original_df=dataframe,
                question_type=question_type,
                sub_q_type=sub_q_type
            )
            return {
                "final_answer": fallback_answer,
                "final_df": dataframe,
                "execution_trace": [],
                "memory_nodes": [],
                "best_path_id": "DIRECT_LLM_FALLBACK",
                "logs": logs + [{"step": "FALLBACK", "reason": "no_operators"}],
                "error": None
            }
        
        # ==================== STEP 2: MCTS - Path Planning ====================
        self.logger.info("\n" + "="*70)
        self.logger.info("STEP 2: MCTS - Path Planning")
        self.logger.info("="*70)
        
        initial_state = {"file_loaded", "schema", "data_loaded"}
        
        paths = self.mcts.plan(
            operators=ado_result.operators,
            initial_state=initial_state,
            num_paths=self.num_paths
        )
        
        self.logger.info(f"Generated {len(paths)} top path(s):")
        for path in paths:
            self.logger.info(f"  {path.path_id}: {' → '.join(path.operators)}")
            self.logger.info(f"    Reward: {path.estimated_reward:.3f}, Structural: {path.structural_score:.3f}")
        
        if self.num_paths == 1:
            self.logger.info("  [Fast Mode: Single path execution]")
        
        logs.append({
            "step": "MCTS",
            "paths_generated": len(paths),
            "top_paths": [p.path_id for p in paths]
        })
        
        if not paths:
            self.logger.warning("No paths generated, attempting retry...")
            # 触发retry机制
            retry_result = self._retry_with_replanning(
                user_query=user_query,
                dataframe=dataframe,
                table_metadata=table_metadata,
                previous_execution_trace=[],
                max_retries=1,
                retry_reason="no_paths"
            )
            
            if retry_result and retry_result.get("final_answer"):
                retry_answer = retry_result["final_answer"]
                # 检查retry是否成功（不是错误消息）
                if not self._is_error_message(retry_answer):
                    self.logger.info(f"✓ Retry successful after no paths! New answer: {retry_answer}")
                    return retry_result
            
            # Retry失败，使用直接LLM回答作为兜底
            self.logger.warning("Retry failed, using direct LLM fallback...")
            question_type = table_metadata.get("question_type", "") if table_metadata else ""
            sub_q_type = table_metadata.get("sub_q_type", "") if table_metadata else ""
            fallback_answer = self.answer_generator._generate_direct_llm_answer(
                user_query=user_query,
                original_df=dataframe,
                question_type=question_type,
                sub_q_type=sub_q_type
            )
            return {
                "final_answer": fallback_answer,
                "final_df": dataframe,
                "execution_trace": [],
                "memory_nodes": [],
                "best_path_id": "DIRECT_LLM_FALLBACK",
                "logs": logs + [{"step": "FALLBACK", "reason": "no_paths"}],
                "error": None
            }
        
        # ==================== STEP 3: SMG - Execute Paths ====================
        self.logger.info("\n" + "="*70)
        self.logger.info("STEP 3: SMG - Execute Paths (with Schema guidance)")
        self.logger.info("="*70)
        
        execution_results = self.smg.execute_paths(
            paths=paths,
            operator_pool=ado_result.operators,
            dataframe=dataframe,
            user_query=user_query,
            table_metadata=table_metadata,
            schema_result=schema_result  # 新增：传入Schema信息
        )
        
        self.logger.info("\n" + "="*70)
        self.logger.info("EXECUTION SUMMARY")
        self.logger.info("="*70)
        self.logger.info(f"Best Path: {execution_results['best_path']}")
        self.logger.info(f"Best Reward: {execution_results['best_reward']:.3f}")
        
        memory_summary = self.smg.get_memory_summary()
        self.logger.info(f"Memory: {memory_summary['total_nodes']} nodes, "
                        f"{memory_summary['success_rate']*100:.1f}% success rate, "
                        f"avg reward: {memory_summary['avg_reward']:.3f}")
        
        logs.append({
            "step": "SMG",
            "best_path": execution_results['best_path'],
            "best_reward": execution_results['best_reward'],
            "memory_summary": memory_summary
        })
        
        # Build execution trace
        execution_trace = []
        for node in execution_results['memory_nodes']:
            execution_trace.append({
                "operation": node.operator_name,
                "code": node.code,
                "success": node.success,
                "error": node.error_message,
                "reward": node.reward_vector.to_dict() if node.reward_vector else None
            })
        
        # ==================== STEP 4: Generate Final Answer ====================
        self.logger.info("\n" + "="*70)
        self.logger.info("STEP 4: Generate Final Answer (with Schema + Markdown table)")
        self.logger.info("="*70)
        
        result_df = execution_results['best_df']
        question_type = table_metadata.get("question_type", "") if table_metadata else ""
        sub_q_type = table_metadata.get("sub_q_type", "") if table_metadata else ""
        
        # 准备markdown表格（如果有schema result）
        markdown_table = None
        if schema_result:
            markdown_table = schema_result.filtered_markdown_table
        
        final_answer = self.answer_generator.generate_answer(
            user_query=user_query,
            result_df=result_df,
            execution_trace=execution_trace,
            question_type=question_type,
            sub_q_type=sub_q_type,
            all_path_results=execution_results.get('all_results', []),
            original_df=dataframe,  # 传入原始数据
            markdown_table=markdown_table,  # 新增：传入markdown表格
            schema_result=schema_result  # 新增：传入schema信息
        )
        
        self.logger.info(f"Generated answer: {final_answer}")
        
        # ==================== STEP 4.5: Retry if Error or No Data Available ====================
        # 检查是否需要retry：错误消息、无数据、或执行失败
        should_retry = False
        retry_reason = None
        
        if final_answer:
            final_answer_lower = final_answer.lower()
            # 检查各种错误情况
            if "no data available" in final_answer_lower:
                should_retry = True
                retry_reason = "no_data"
            elif "no operators extracted" in final_answer_lower:
                should_retry = True
                retry_reason = "no_operators"
            elif "no execution paths generated" in final_answer_lower:
                should_retry = True
                retry_reason = "no_paths"
            elif "execution failed" in final_answer_lower:
                should_retry = True
                retry_reason = "execution_failed"
            elif self._is_error_message(final_answer):
                should_retry = True
                retry_reason = "error_message"
        
        # 检查结果DataFrame是否为空
        if result_df is not None and result_df.empty:
            should_retry = True
            retry_reason = retry_reason or "empty_result"
        
        if should_retry:
            self.logger.warning(f"⚠️  Detected issue ({retry_reason}), attempting retry...")
            
            retry_result = self._retry_with_replanning(
                user_query=user_query,
                dataframe=dataframe,
                table_metadata=table_metadata,
                previous_execution_trace=execution_trace,
                max_retries=1,  # 只重试一次，避免无限循环
                retry_reason=retry_reason
            )
            
            if retry_result and retry_result.get("final_answer"):
                retry_answer = retry_result["final_answer"]
                # 检查retry是否成功（不是错误消息）
                if not self._is_error_message(retry_answer) and "no data available" not in retry_answer.lower():
                    self.logger.info(f"✓ Retry successful! New answer: {retry_answer[:100]}...")
                    final_answer = retry_answer
                    result_df = retry_result.get("final_df", result_df)
                    execution_trace = retry_result.get("execution_trace", execution_trace)
                    # 合并logs
                    if retry_result.get("logs"):
                        logs.extend(retry_result["logs"])
                else:
                    self.logger.warning(f"⚠️  Retry still resulted in error: {retry_answer[:100]}")
                    # Retry失败，使用直接LLM回答作为兜底
                    self.logger.info("🔄 Falling back to direct LLM answer (bypassing code execution)...")
                    fallback_answer = self.answer_generator._generate_direct_llm_answer(
                        user_query=user_query,
                        original_df=dataframe,
                        question_type=question_type,
                        sub_q_type=sub_q_type
                    )
                    if fallback_answer and not self._is_error_message(fallback_answer):
                        self.logger.info(f"✓ Direct LLM fallback successful: {fallback_answer[:100]}...")
                        final_answer = fallback_answer
                    else:
                        self.logger.warning("⚠️  Direct LLM fallback also failed")
            else:
                self.logger.warning("⚠️  Retry failed or returned no result")
                # Retry失败，使用直接LLM回答作为兜底
                self.logger.info("🔄 Falling back to direct LLM answer (bypassing code execution)...")
                fallback_answer = self.answer_generator._generate_direct_llm_answer(
                    user_query=user_query,
                    original_df=dataframe,
                    question_type=question_type,
                    sub_q_type=sub_q_type
                )
                if fallback_answer and not self._is_error_message(fallback_answer):
                    self.logger.info(f"✓ Direct LLM fallback successful: {fallback_answer[:100]}...")
                    final_answer = fallback_answer
                else:
                    self.logger.warning("⚠️  Direct LLM fallback also failed")
        
        # ==================== STEP 5: Save Experience ====================
        if self.experience_manager:
            self.logger.info("\n" + "="*70)
            self.logger.info("STEP 5: Save Experience")
            self.logger.info("="*70)
            
            try:
                # 保存MCTS路径经验
                best_path_result = execution_results.get('all_results', [{}])[0]
                if best_path_result:
                    path_operators = best_path_result.get('path_id', '').replace('PATH_', '').split(' → ')
                    success = best_path_result.get('success_count', 0) > 0
                    reward = best_path_result.get('cumulative_reward', 0.0)
                    
                    self.experience_manager.update_mcts_prior(path_operators, success, reward)
                
                # 保存SMG执行记录
                for node in execution_results['memory_nodes']:
                    self.experience_manager.add_smg_record(
                        operator=node.operator_name,
                        code=node.code,
                        success=node.success,
                        reward=node.reward_vector.to_dict() if node.reward_vector else {},
                        error=node.error_message
                    )
                
                # 保存到磁盘
                self.experience_manager.save()
                
                self.logger.info("✓ Experience saved successfully")
                
            except Exception as e:
                self.logger.warning(f"⚠️  Failed to save experience: {e}")
        
        # Get token statistics
        token_stats = self.llm_client.get_token_stats()
        
        return {
            "final_answer": final_answer,  # Natural language answer
            "final_df": result_df,  # Keep DataFrame for debugging
            "execution_trace": execution_trace,
            "memory_nodes": execution_results['memory_nodes'],
            "best_path_id": execution_results['best_path'],
            "best_reward": execution_results['best_reward'],
            "all_path_results": execution_results['all_results'],
            "schema_linking": schema_result,  # 新增：返回schema信息
            "logs": logs,
            "llm_calls": self.llm_client.get_call_count(),  # LLM调用次数
            "output_tokens": token_stats['output_tokens'],  # 输出token数
            "input_tokens": token_stats['input_tokens'],  # 输入token数
            "total_tokens": token_stats['total_tokens']  # 总token数
        }
    
    def _is_error_message(self, answer: str) -> bool:
        """
        检查答案是否是错误消息
        
        Args:
            answer: 答案字符串
            
        Returns:
            True if answer is an error message
        """
        if not answer:
            return True
        
        answer_lower = answer.lower()
        error_indicators = [
            "no operators extracted",
            "no execution paths generated",
            "execution failed",
            "no answer generated",
            "error:",
            "failed:",
            "exception:"
        ]
        
        return any(indicator in answer_lower for indicator in error_indicators)
    
    def _retry_with_replanning(
        self,
        user_query: str,
        dataframe: pd.DataFrame,
        table_metadata: Optional[Dict[str, Any]],
        previous_execution_trace: list,
        max_retries: int = 1,
        retry_reason: str = None
    ) -> Optional[Dict[str, Any]]:
        """
        当出现错误或"No data available"时，重新规划或重新查找数据
        
        Args:
            user_query: 用户问题
            dataframe: 原始数据
            table_metadata: 表格元数据
            previous_execution_trace: 之前的执行轨迹
            max_retries: 最大重试次数
            retry_reason: 重试原因（用于日志和策略选择）
            
        Returns:
            重试后的结果，如果失败则返回None
        """
        self.logger.info("\n" + "="*70)
        self.logger.info(f"RETRY: Replanning with Different Strategy (Reason: {retry_reason})")
        self.logger.info("="*70)
        
        try:
            # 根据retry_reason选择不同的策略
            if retry_reason == "no_operators":
                # 策略1: 如果之前没有提取到operators，尝试更宽松的提取
                self.logger.info("Strategy 1: Re-extracting operators with relaxed constraints...")
                # 可以尝试重新构建更详细的metadata
                enhanced_metadata = table_metadata.copy() if table_metadata else {}
                if dataframe is not None and not dataframe.empty:
                    enhanced_metadata.update({
                        "sample_data": dataframe.head(20).to_dict('records')[:5],  # 提供样本数据
                        "column_examples": {col: str(dataframe[col].dropna().iloc[0]) if len(dataframe[col].dropna()) > 0 else "" 
                                          for col in dataframe.columns[:10]}  # 提供列示例
                    })
            else:
                # 策略1: 使用更宽松的查询条件重新执行ADO
                self.logger.info("Strategy 1: Re-extracting operators...")
                enhanced_metadata = table_metadata
            
            # 重新执行ADO，传入smg_module以利用历史经验
            ado_result = self.ado.extract_operators(
                user_query=user_query,
                table_metadata=enhanced_metadata,
                smg_module=self.smg
            )
            
            if not ado_result.operators:
                self.logger.warning("No operators extracted in retry")
                return None
            
            self.logger.info(f"Re-extracted {len(ado_result.operators)} operators")
            
            # 策略2: 尝试不同的路径规划
            initial_state = {"file_loaded", "schema", "data_loaded"}
            
            # 生成更多路径供选择
            paths = self.mcts.plan(
                operators=ado_result.operators,
                initial_state=initial_state,
                num_paths=min(self.num_paths + 1, 5)  # 生成更多路径
            )
            
            if not paths:
                self.logger.warning("No paths generated in retry")
                return None
            
            self.logger.info(f"Generated {len(paths)} alternative path(s) for retry")
            
            # 策略3: 执行新路径
            execution_results = self.smg.execute_paths(
                paths=paths,
                operator_pool=ado_result.operators,
                dataframe=dataframe,
                user_query=user_query,
                table_metadata=table_metadata
            )
            
            result_df = execution_results['best_df']
            
            # 如果新结果仍然为空，尝试从原始数据直接提取
            if result_df is None or result_df.empty:
                self.logger.warning("Retry execution still resulted in empty DataFrame")
                # 尝试使用原始数据生成答案
                question_type = table_metadata.get("question_type", "") if table_metadata else ""
                sub_q_type = table_metadata.get("sub_q_type", "") if table_metadata else ""
                final_answer = self.answer_generator.generate_answer(
                    user_query=user_query,
                    result_df=dataframe.head(100),  # 使用原始数据的前100行
                    execution_trace=previous_execution_trace,
                    question_type=question_type,
                    sub_q_type=sub_q_type,
                    all_path_results=[],
                    original_df=dataframe
                )
                
                if "no data available" not in final_answer.lower():
                    return {
                        "final_answer": final_answer,
                        "final_df": dataframe.head(100),
                        "execution_trace": previous_execution_trace,
                        "memory_nodes": execution_results['memory_nodes'],
                        "best_path_id": "RETRY_ORIGINAL_DATA",
                        "best_reward": 0.0,
                        "all_path_results": [],
                        "logs": [{"step": "RETRY", "strategy": "use_original_data"}]
                    }
                return None
            
            # 使用新结果生成答案
            question_type = table_metadata.get("question_type", "") if table_metadata else ""
            sub_q_type = table_metadata.get("sub_q_type", "") if table_metadata else ""
            final_answer = self.answer_generator.generate_answer(
                user_query=user_query,
                result_df=result_df,
                execution_trace=execution_results.get('execution_trace', []),
                question_type=question_type,
                sub_q_type=sub_q_type,
                all_path_results=execution_results.get('all_results', []),
                original_df=dataframe
            )
            
            return {
                "final_answer": final_answer,
                "final_df": result_df,
                "execution_trace": execution_results.get('execution_trace', []),
                "memory_nodes": execution_results['memory_nodes'],
                "best_path_id": execution_results['best_path'],
                "best_reward": execution_results['best_reward'],
                "all_path_results": execution_results.get('all_results', []),
                "logs": [{"step": "RETRY", "strategy": "replanning", "paths_tried": len(paths)}]
            }
            
        except Exception as e:
            self.logger.error(f"Error during retry: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return None
    
    def _extract_metadata(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Extract metadata from DataFrame"""
        if df is None or df.empty:
            return {
                "column_names": [],
                "column_types": {},
                "row_count": 0
            }
        
        return {
            "column_names": list(df.columns),
            "column_types": {col: str(dtype) for col, dtype in df.dtypes.items()},
            "row_count": len(df),
            "shape": df.shape
        }
    
    def get_memory_stats(self) -> Dict[str, Any]:
        """Get statistics from SMG memory"""
        return self.smg.get_memory_summary()
    
    def clear_memory(self):
        """Clear SMG memory"""
        self.smg.clear_memory()
    
    def save_session(self, session_id: str):
        """Save current session to persistent memory"""
        self.smg.save_memory_to_persistent(session_id)
        self.logger.info(f"Session {session_id} saved to persistent memory")
    
    def load_session(self, session_id: str):
        """Load session from persistent memory"""
        self.smg.load_memory_from_persistent(session_id)
        self.logger.info(f"Session {session_id} loaded from persistent memory")


def test_dtr_framework():
    """Test the DTR framework end-to-end"""
    import pandas as pd
    import logging
    
    # Setup logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("DTR")
    
    # Mock LLM
    class MockLLM:
        def call_api(self, prompt):
            # ADO response
            if "Available Operators" in prompt:
                return '''{
                    "operators": ["SELECT_COLUMNS", "GROUP_BY", "AGGREGATE", "SORT_VALUES"],
                    "reasoning": "Need to select relevant columns, group by department, aggregate salaries, and sort results"
                }'''
            
            # Code generation responses
            if "SELECT_COLUMNS" in prompt:
                return '''```python
df = df[['department', 'salary']]
```'''
            elif "GROUP_BY" in prompt:
                return '''```python
df = df.groupby('department')['salary'].mean().reset_index()
df.columns = ['department', 'avg_salary']
```'''
            elif "AGGREGATE" in prompt or "SORT_VALUES" in prompt:
                return '''```python
df = df.sort_values('avg_salary', ascending=False)
```'''
            
            # Reward evaluation
            elif "execution_success" in prompt:
                return '''{
                    "execution_success": 1.0,
                    "query_satisfaction": 0.9,
                    "code_reasonableness": 0.85,
                    "efficiency": 0.8,
                    "error_severity": 0.0,
                    "explanation": "Successfully executed"
                }'''
            
            return "pass"
    
    # Create test data
    df = pd.DataFrame({
        'employee_id': range(1, 11),
        'name': ['Alice', 'Bob', 'Charlie', 'David', 'Eve', 
                 'Frank', 'Grace', 'Henry', 'Ivy', 'Jack'],
        'department': ['Sales', 'Sales', 'IT', 'IT', 'HR', 
                       'HR', 'Sales', 'IT', 'HR', 'Sales'],
        'salary': [50000, 55000, 60000, 65000, 45000,
                   48000, 52000, 62000, 46000, 54000]
    })
    
    print("Test Data:")
    print(df)
    print()
    
    # Initialize framework
    llm = MockLLM()
    dtr = DTRFramework(llm, logger)
    
    # Process query
    print("\n" + "="*70)
    print("TESTING DTR FRAMEWORK")
    print("="*70 + "\n")
    
    result = dtr.process_query(
        user_query="What is the average salary by department, sorted from highest to lowest?",
        dataframe=df
    )
    
    # Display results
    print("\n" + "="*70)
    print("FINAL RESULTS")
    print("="*70)
    
    if result["final_answer"] is not None:
        print("\nFinal DataFrame:")
        print(result["final_answer"])
    
    print(f"\nBest Path: {result['best_path_id']}")
    print(f"Best Reward: {result.get('best_reward', 0):.3f}")
    
    print("\nExecution Trace:")
    for i, step in enumerate(result["execution_trace"], 1):
        status = "✓" if step["success"] else "✗"
        print(f"  {i}. {step['operation']} {status}")
        if step.get("reward"):
            print(f"     Reward: {step['reward'].get('total_score', 0):.3f}")
    
    print("\nMemory Stats:")
    stats = dtr.get_memory_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    return result


if __name__ == "__main__":
    test_dtr_framework()

