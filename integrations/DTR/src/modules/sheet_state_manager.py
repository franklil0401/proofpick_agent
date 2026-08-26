"""
Sheet State Manager - Sheet状态管理器

负责管理多个sheet的当前状态，支持状态更新、查询和历史追踪
"""

from typing import Dict, List, Optional, Any
import pandas as pd
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SheetModificationRecord:
    """Sheet修改记录"""
    iteration: int
    timestamp: datetime
    operation_summary: str
    shape_before: tuple
    shape_after: tuple


class SheetStateManager:
    """
    Sheet状态管理器
    
    管理所有sheet的当前状态，支持：
    - 状态初始化
    - 状态更新
    - 状态查询
    - 修改历史追踪
    """
    
    def __init__(self, multi_sheet_context):
        """
        初始化状态管理器
        
        Args:
            multi_sheet_context: MultiSheetContext对象
        """
        self.context = multi_sheet_context
        self.modification_history: Dict[str, List[SheetModificationRecord]] = {
            name: [] for name in multi_sheet_context.get_sheet_names()
        }
    
    def get_sheet_names(self) -> List[str]:
        """获取所有sheet名称"""
        return self.context.get_sheet_names()
    
    def get_default_sheet(self) -> str:
        """获取默认sheet名称"""
        return self.context.default_sheet
    
    def get_current_df(self, sheet_name: Optional[str] = None) -> pd.DataFrame:
        """
        获取指定sheet的当前DataFrame
        
        Args:
            sheet_name: Sheet名称，None表示使用默认sheet
            
        Returns:
            DataFrame副本
        """
        if sheet_name is None:
            sheet_name = self.context.default_sheet
        
        return self.context.get_current_df(sheet_name).copy()
    
    def get_original_df(self, sheet_name: Optional[str] = None) -> pd.DataFrame:
        """
        获取指定sheet的原始DataFrame（只读）
        
        Args:
            sheet_name: Sheet名称，None表示使用默认sheet
            
        Returns:
            原始DataFrame副本
        """
        if sheet_name is None:
            sheet_name = self.context.default_sheet
        
        return self.context.get_original_df(sheet_name).copy()
    
    def update_sheet(
        self,
        sheet_name: str,
        new_df: pd.DataFrame,
        iteration: int,
        operation_summary: str = "Code execution"
    ) -> bool:
        """
        更新指定sheet的DataFrame
        
        Args:
            sheet_name: Sheet名称
            new_df: 新的DataFrame
            iteration: 当前迭代轮次
            operation_summary: 操作摘要
            
        Returns:
            是否更新成功
        """
        try:
            # 获取更新前的shape
            state = self.context.get_state(sheet_name)
            shape_before = state.current_df.shape
            
            # 更新状态
            self.context.update_sheet(sheet_name, new_df, iteration)
            
            # 记录修改历史
            record = SheetModificationRecord(
                iteration=iteration,
                timestamp=datetime.now(),
                operation_summary=operation_summary,
                shape_before=shape_before,
                shape_after=new_df.shape
            )
            self.modification_history[sheet_name].append(record)
            
            return True
            
        except Exception as e:
            print(f"❌ Failed to update sheet '{sheet_name}': {e}")
            return False
    
    def add_new_sheet(
        self,
        sheet_name: str,
        df: pd.DataFrame,
        iteration: int,
        operation_summary: str = "Created by code execution"
    ) -> bool:
        """
        添加新的sheet
        
        Args:
            sheet_name: Sheet名称
            df: DataFrame数据
            iteration: 当前迭代轮次
            operation_summary: 操作摘要
            
        Returns:
            是否添加成功
        """
        try:
            # 检查是否已存在
            if self.has_sheet(sheet_name):
                print(f"⚠️  Sheet '{sheet_name}' already exists, use update_sheet instead")
                return False
            
            # 添加到context
            from integrations.DTR.src.modules.multi_sheet_loader import SheetState
            
            new_state = SheetState(
                name=sheet_name,  # 添加name参数
                original_df=df.copy(),
                current_df=df.copy(),
                metadata={"created_at_iteration": iteration}
            )
            
            self.context.sheet_states[sheet_name] = new_state
            self.context.total_sheets += 1
            
            # 初始化修改历史
            self.modification_history[sheet_name] = []
            
            # 记录创建记录
            record = SheetModificationRecord(
                iteration=iteration,
                timestamp=datetime.now(),
                operation_summary=operation_summary,
                shape_before=(0, 0),
                shape_after=df.shape
            )
            self.modification_history[sheet_name].append(record)
            
            print(f"✨ Successfully added new sheet '{sheet_name}': {df.shape}")
            return True
            
        except Exception as e:
            print(f"❌ Failed to add new sheet '{sheet_name}': {e}")
            return False
    
    def get_sheet_state_summary(self, sheet_name: str) -> str:
        """
        获取指定sheet的状态摘要
        
        Args:
            sheet_name: Sheet名称
            
        Returns:
            格式化的状态摘要
        """
        state = self.context.get_state(sheet_name)
        
        lines = []
        lines.append(f"**{sheet_name}**:")
        lines.append(f"  - Current shape: {state.current_df.shape[0]} rows × {state.current_df.shape[1]} cols")
        lines.append(f"  - Modified: {state.modification_count} times")
        
        if state.modification_count > 0:
            lines.append(f"  - Last modified at iteration: {state.last_modified_iteration}")
            
            # 显示最近的修改记录
            if sheet_name in self.modification_history and self.modification_history[sheet_name]:
                last_record = self.modification_history[sheet_name][-1]
                lines.append(f"  - Last operation: {last_record.operation_summary}")
                if last_record.shape_before != last_record.shape_after:
                    lines.append(f"    Shape changed: {last_record.shape_before} → {last_record.shape_after}")
        
        return "\n".join(lines)
    
    def get_all_states_summary(self, include_unmodified: bool = True) -> str:
        """
        获取所有sheet的状态摘要
        
        Args:
            include_unmodified: 是否包含未修改的sheet
            
        Returns:
            格式化的状态摘要
        """
        lines = []
        lines.append("## 📋 Sheet States Summary")
        lines.append(f"Total sheets: {self.context.total_sheets}")
        lines.append(f"Default sheet: {self.context.default_sheet}")
        lines.append("")
        
        modified_count = 0
        for sheet_name in self.context.get_sheet_names():
            state = self.context.get_state(sheet_name)
            
            if state.modification_count > 0:
                modified_count += 1
            
            # 跳过未修改的sheet（如果设置了）
            if not include_unmodified and state.modification_count == 0:
                continue
            
            # 添加前缀标记
            prefix = "→" if sheet_name == self.context.default_sheet else " "
            mod_marker = "✏️ " if state.modification_count > 0 else ""
            
            lines.append(f"{prefix} {mod_marker}{self.get_sheet_state_summary(sheet_name)}")
            lines.append("")
        
        if modified_count > 0:
            lines.append(f"**Summary**: {modified_count} sheet(s) have been modified")
        else:
            lines.append("**Summary**: No sheets have been modified yet")
        
        return "\n".join(lines)
    
    def get_modification_history(self, sheet_name: str) -> List[SheetModificationRecord]:
        """
        获取指定sheet的修改历史
        
        Args:
            sheet_name: Sheet名称
            
        Returns:
            修改记录列表
        """
        return self.modification_history.get(sheet_name, [])
    
    def get_sheets_dict_for_execution(self) -> Dict[str, pd.DataFrame]:
        """
        获取所有sheet的当前DataFrame（用于代码执行环境）
        
        Returns:
            {sheet_name: df_copy} 字典
        """
        sheets_dict = {}
        for sheet_name in self.context.get_sheet_names():
            sheets_dict[sheet_name] = self.context.get_current_df(sheet_name).copy()
        return sheets_dict
    
    def has_sheet(self, sheet_name: str) -> bool:
        """
        检查是否存在指定的sheet
        
        Args:
            sheet_name: Sheet名称
            
        Returns:
            是否存在
        """
        return sheet_name in self.context.sheet_states
    
    def get_sheet_metadata(self, sheet_name: str) -> Dict[str, Any]:
        """
        获取指定sheet的元数据
        
        Args:
            sheet_name: Sheet名称
            
        Returns:
            元数据字典
        """
        state = self.context.get_state(sheet_name)
        return state.metadata
    
    def reset_sheet(self, sheet_name: str) -> bool:
        """
        重置指定sheet到原始状态
        
        Args:
            sheet_name: Sheet名称
            
        Returns:
            是否重置成功
        """
        try:
            state = self.context.get_state(sheet_name)
            original_df = state.original_df.copy()
            
            # 重置到原始状态
            state.current_df = original_df
            state.modification_count = 0
            state.last_modified_iteration = 0
            
            # 清空修改历史
            self.modification_history[sheet_name] = []
            
            return True
            
        except Exception as e:
            print(f"❌ Failed to reset sheet '{sheet_name}': {e}")
            return False
    
    def get_compact_summary(self) -> str:
        """
        获取紧凑的状态摘要（用于反馈）
        
        Returns:
            一行或几行的简洁摘要
        """
        modified_sheets = [
            name for name in self.context.get_sheet_names()
            if self.context.get_state(name).modification_count > 0
        ]
        
        if not modified_sheets:
            return f"No sheets modified. Default sheet: {self.context.default_sheet} ({self.context.get_current_df(self.context.default_sheet).shape})"
        
        summaries = []
        for sheet_name in modified_sheets:
            state = self.context.get_state(sheet_name)
            summaries.append(f"{sheet_name}({state.current_df.shape[0]}×{state.current_df.shape[1]})")
        
        return f"Modified sheets: {', '.join(summaries)}"


if __name__ == "__main__":
    # 测试代码
    print("SheetStateManager module loaded successfully")
