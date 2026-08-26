"""
ADG Benchmark Runner V4 - 分步执行 + 丰富上下文
"""

import os
import sys
import json
import datetime
import argparse
import yaml
import asyncio
from tqdm import tqdm
from pathlib import Path
import concurrent.futures
from threading import Lock
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal

project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

# 添加当前模块的父目录到 sys.path
integration_root = Path(__file__).parent
sys.path.insert(0, str(integration_root))

from utils.llm_client import LLMClient
from src.modules.smg_autonomous import SMGAutonomousModule
from src.modules.multi_sheet_loader import MultiSheetLoader, MultiSheetContext
from src.modules.sheet_state_manager import SheetStateManager
from utils.logger import logger
from utils.smart_table_processor import SmartTableProcessor
from utils.meta_extractor import MetaExtractor

from utu.agents.common import TaskRecorder, QueueCompleteSentinel
from utu.tools.memory_toolkit import VectorMemoryToolkit



@dataclass
class ExcelAgentStreamEvent:
    """ExcelAgent 流式事件"""
    name: Literal[
        "excel_agent.plan.start",
        "excel_agent.plan.delta",
        "excel_agent.plan.done",
        "excel_agent.task.start",
        "excel_agent.task.delta",
        "excel_agent.task.done",
        "excel_agent.answer.start",
        "excel_agent.answer.delta",
        "excel_agent.answer.done",
    ]
    item: dict | None = None
    type: Literal["excel_agent_stream_event"] = "excel_agent_stream_event"


@dataclass
class ExcelAgentRecorder(TaskRecorder):
    """用于记录和流式传输 ExcelAgent 的执行结果
    
    继承自 TaskRecorder，保持与其他 Agent 接口一致
    """
    # ExcelAgent 特有字段
    question_type: str = ""
    execution_trace: list = field(default_factory=list)


class ExcelAgent:

    def __init__(self, config):
        self.config = self._load_config(config)
        # workflow 和 instance 将在运行时根据 event_callback 创建
        self.workflow = None
        self.instance = None
        self._memory_toolkit = None

    def set_memory_toolkit(self, memory_toolkit: "VectorMemoryToolkit") -> None:
        """Set the memory toolkit for this agent.

        Args:
            memory_toolkit: VectorMemoryToolkit instance for memory operations.
        """
        self._memory_toolkit = memory_toolkit

    @property
    def memory_toolkit(self) -> "VectorMemoryToolkit | None":
        """Get the memory toolkit if set."""
        return self._memory_toolkit

    def _load_config(self, config):
        with open(config, 'r') as f:
            return yaml.safe_load(f)
    
    def _build_workflow(self, event_callback=None):
        """构建 workflow，支持传入事件回调"""
        # 初始化LLM客户端
        llm_client = LLMClient(
            model=os.getenv("UTU_LLM_MODEL", "deepseek-v3"),
            base_url=os.getenv("UTU_LLM_BASE_URL", "https://api.lkeap.cloud.tencent.com/v1"),
            api_key=os.getenv("UTU_LLM_API_KEY", ""),
            temperature=0.0,
            max_tokens=4096
        )

        smg = SMGAutonomousModule(llm_client, event_callback=event_callback, reward_evaluator=None)
        # 重置token计数
        llm_client.reset_call_count()
        return smg



    async def run(self, input, question_type=None):
        """运行查询（异步版本）"""
        recorder = self.run_streamed(input, question_type)
        async for _ in recorder.stream_events():
            pass
        return {
            'question': recorder.task,
            'FileName': self._get_file_name(),
            'model_answer': recorder.final_output,
        }
    
    def load_data(self, table_file):
        """加载数据（支持多sheet）
        
        Returns:
            (multi_sheet_context, table_info_str)
        """
        import pandas as pd
        logger.info(f"📂 加载表格: {table_file}")
        
        # 检查文件类型
        if table_file.suffix not in ['.xlsx', '.xls', '.csv']:
            raise ValueError(f"Unsupported file type: {table_file.suffix}")
        
        # CSV文件：转换为单sheet的MultiSheetContext
        if table_file.suffix == '.csv':
            df = pd.read_csv(table_file)
            
            if df is None or df.empty:
                logger.error("❌ 表格加载失败或为空")
                return None, None
            
            # 创建单sheet的context
            from src.modules.multi_sheet_loader import SheetState, MultiSheetContext
            
            state = SheetState(
                name="Sheet1",
                original_df=df.copy(),
                current_df=df.copy(),
                metadata={
                    "sheet_name": "Sheet1",
                    "shape": df.shape,
                    "columns": list(df.columns),
                    "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()}
                }
            )
            
            context = MultiSheetContext(
                file_path=str(table_file),
                sheet_states={"Sheet1": state},
                default_sheet="Sheet1",
                total_sheets=1
            )
            
            # 生成表格信息
            table_info = self._generate_table_info(context)
            return context, table_info
        
        # Excel文件：使用MultiSheetLoader加载
        try:
            # 初始化处理器
            processor = SmartTableProcessor()
            meta_extractor = MetaExtractor()
            
            # 加载所有sheet
            loader = MultiSheetLoader(max_preview_rows=6)
            context = loader.load_excel_file(
                str(table_file),
                processor=processor,
                meta_extractor=meta_extractor
            )
            
            # 生成表格信息
            table_info = self._generate_table_info(context)
            
            return context, table_info
            
        except Exception as e:
            logger.error(f"❌ 多sheet加载失败: {e}")
            # Fallback: 尝试简单加载
            try:
                df = pd.read_excel(table_file)
                
                from src.modules.multi_sheet_loader import SheetState, MultiSheetContext
                
                state = SheetState(
                    name="Sheet1",
                    original_df=df.copy(),
                    current_df=df.copy(),
                    metadata={
                        "sheet_name": "Sheet1",
                        "shape": df.shape,
                        "columns": list(df.columns),
                        "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()}
                    }
                )
                
                context = MultiSheetContext(
                    file_path=str(table_file),
                    sheet_states={"Sheet1": state},
                    default_sheet="Sheet1",
                    total_sheets=1
                )
                
                table_info = self._generate_table_info(context)
                return context, table_info
                
            except Exception as e2:
                logger.error(f"❌ Fallback加载也失败: {e2}")
                return None, None
    
    def _generate_table_info(self, context: MultiSheetContext) -> str:
        """生成表格信息字符串（用于日志）"""
        lines = []
        lines.append(f"📁 文件: {Path(context.file_path).name}")
        lines.append(f"📊 Sheets: {context.total_sheets}")
        
        for sheet_name, state in context.sheet_states.items():
            df = state.current_df
            prefix = "→" if sheet_name == context.default_sheet else " "
            lines.append(f"\n{prefix} Sheet '{sheet_name}':")
            lines.append(f"  维度: {df.shape[0]} 行 × {df.shape[1]} 列")
            lines.append(f"  列名: {', '.join(df.columns.tolist()[:10])}")
            if len(df.columns) > 10:
                lines.append(f"       ... ({len(df.columns) - 10} more columns)")
            
            lines.append(f"\n  数据类型:")
            for col, dtype in list(df.dtypes.items())[:5]:
                lines.append(f"    • {col}: {dtype}")
            if len(df.dtypes) > 5:
                lines.append(f"    ... ({len(df.dtypes) - 5} more columns)")
            
            lines.append(f"\n  数据预览 (前5行):")
            lines.append(df.head().to_string())
        
        return "\n".join(lines)

    def run_streamed(self, input, question_type=None, use_memory: bool = True) -> ExcelAgentRecorder:
        """流式运行查询"""
        recorder = ExcelAgentRecorder(task=input, question_type=question_type, trace_id="")
        recorder._run_impl_task = asyncio.create_task(self._start_streaming(recorder, use_memory=use_memory))
        return recorder
    
    def _get_file_name(self):
        """获取文件名"""
        file_path = os.environ.get("FILE_PATH", None)
        if file_path:
            return Path(file_path.split(",")[0]).stem
        return "unknown"
    
    async def _start_streaming(self, recorder: ExcelAgentRecorder, use_memory: bool = True):
        """异步执行流程"""
        try:
            # 从环境变量读取全局配置，覆盖传入参数
            env_memory_setting = os.environ.get("memoryEnabled", "false").lower() == "true"
            use_memory = env_memory_setting
            logger.info(f"[ExcelAgent] use_memory from env: {use_memory}")
            logger.info(f"[ExcelAgent] self._memory_toolkit: {self._memory_toolkit}")
            question = recorder.task
            question_type = recorder.question_type
            original_question = question  # 保存原始问题用于 episodic memory

            if use_memory:
                logger.info(f"[ExcelAgent] use_memory: {use_memory}")

            if use_memory and self._memory_toolkit:
                await self._memory_toolkit.store_working_memory(question, role="user")
                logger.debug("Stored user question to working memory")

                # 使用统一的 memory 检索方法
                memory_contexts = await self._memory_toolkit.retrieve_all_context(
                    query=question,
                    include_skills=False,
                )
                memory_context = memory_contexts["memory_context"]

                if memory_context:
                    logger.info(f"Retrieved memory context: {len(memory_context)} chars")

                enhanced_input = f"# 相关历史上下文\n{memory_context}\n\n---\n# 当前问题\n{question}"
                recorder.task = enhanced_input
                question = enhanced_input

            file_path = os.environ.get("FILE_PATH", None)
            file_path = Path(file_path.split(",")[0])
            file_name = file_path.stem
            
            # 获取当前事件循环，供回调函数使用
            current_loop = asyncio.get_running_loop()
            
            # 定义线程安全的事件回调函数
            def event_callback(name: str, event_data: dict):
                """接收来自 workflow 的事件并转发（线程安全）"""
                try:
                    event = ExcelAgentStreamEvent(
                        name=name,
                        item=event_data
                    )
                    # 使用 call_soon_threadsafe 确保跨线程安全
                    current_loop.call_soon_threadsafe(
                        recorder._event_queue.put_nowait,
                        event
                    )
                    logger.debug(f"Event sent from thread: {event_data.get('step', 'unknown')}")
                except Exception as e:
                    logger.warning(f"Failed to send event from callback: {e}")
            

            # 发送开始事件
            recorder._event_queue.put_nowait(
                ExcelAgentStreamEvent(
                    name="excel_agent.plan.start",
                    item={
                        "question": question,
                        "file_path": str(file_path)
                    }
                )
            )

            recorder._event_queue.put_nowait(
                ExcelAgentStreamEvent(
                    name="excel_agent.plan.delta",
                    item={
                        "content": "Loading data..."
                    }
                )
            )

            # 加载数据（支持多sheet）
            context, table_info = await asyncio.to_thread(self.load_data, file_path)
            
            if context is None:
                raise ValueError("Failed to load data")
            
            recorder._event_queue.put_nowait(
                ExcelAgentStreamEvent(
                    name="excel_agent.plan.delta",
                    item={
                        "content": table_info,
                        "clean": True
                    }
                )
            )

            # 构建metadata
            sub_q_type = question_type or ""  # 如果没有提供，使用空字符串
            max_iterations = self.config.get('config', {}).get('max_iterations', 10)  # 从配置读取，默认10
            
            # 从context提取metadata（使用默认sheet的信息）
            default_state = context.get_state(context.default_sheet)
            df = default_state.current_df
            
            metadata = {
                "column_names": list(df.columns),
                "column_types": {col: str(dtype) for col, dtype in df.dtypes.items()},
                "row_count": len(df),
                "shape": df.shape,
                "question_type": question_type,
                "sub_q_type": sub_q_type,
                # 添加多sheet信息
                "total_sheets": context.total_sheets,
                "sheet_names": context.get_sheet_names(),
                "default_sheet": context.default_sheet
            }

            smg = self._build_workflow(event_callback=event_callback)

            try:
                result = await current_loop.run_in_executor(
                    None,
                    lambda: smg.execute_with_autonomous_loop(
                        operator_sequence=[],
                        operator_pool=[],
                        sheet_context=context,  # 传递MultiSheetContext
                        user_query=question,
                        table_metadata=metadata,
                        schema_result=None,
                        max_iterations=max_iterations
                    )
                )
                final_answer = result.get("final_answer", "")
                execution_trace = result.get("execution_trace", [])
            except Exception as e:
                if "Recursion limit" in str(e):
                    logger.warning(f"Query hit recursion limit.")
                    final_answer = "[Final Answer]: Processing timeout"
                    execution_trace = []
                else:
                    raise e
            
            # 更新 recorder
            recorder.final_output = final_answer
            recorder.execution_trace = execution_trace

            final_output = str(recorder.final_output or "")
            logger.debug(f"Final output: {final_output}")

            # if use_memory and self._memory_toolkit:
            #     # 存储 working memory
            #     await self._memory_toolkit.store_working_memory(final_output, role="assistant")
            #     logger.debug("Saved model output to memory")

            # 存储到 Memory（包括 episodic memory）
            if use_memory and self._memory_toolkit:
                try:
                    # 存储 working memory
                    await self._memory_toolkit.store_working_memory(final_output, role="assistant")
                    
                    # 存储到 episodic memory（持久化）
                    # 恢复原始问题（去除上下文注入部分）
                    clean_question = original_question
                    if "\n# 当前问题\n" in str(recorder.task):
                        clean_question = str(recorder.task).split("\n# 当前问题\n")[-1]
                    
                    await self._memory_toolkit.save_conversation_to_episodic(
                        question=clean_question,
                        answer=final_output,
                        importance_score=0.6,  # Excel 分析通常比较重要
                    )
                    logger.debug("Saved conversation to episodic memory")
                except Exception as e:
                    logger.warning(f"Memory storage error: {e}")
            
            # 发送完成事件
            recorder._event_queue.put_nowait(
                ExcelAgentStreamEvent(
                    name="excel_agent.answer.delta",
                    item={
                        "type": "answer_generation",
                        "content": recorder.final_output
                    }
                )
            )
            
        except Exception as e:
            logger.error(f"Error processing task: {str(e)}")
            recorder._event_queue.put_nowait(QueueCompleteSentinel())
            recorder._is_complete = True
            raise e
        finally:
            recorder._event_queue.put_nowait(QueueCompleteSentinel())
            recorder._is_complete = True

if __name__ == "__main__":

    async def main():
        query = "/Users/felix/Documents/GitProjects/YoutuRAG_Benchmark/data/data_0109/多表mini/excels/奥运会参赛队伍.xlsx"
        agent = ExcelAgent(config="configs/agents/ragref/excel/excel.yaml")
        
        # 使用异步流式调用
        rec = agent.run_streamed(query)
        async for event in rec.stream_events():
            print(f"Event: {event}")
        
        print(f"\nFinal Answer:\n{rec.final_output}")
    
    asyncio.run(main())

