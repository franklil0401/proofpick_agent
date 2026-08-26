"""
Multi-Sheet Loader - 多Sheet表格加载器

负责加载Excel文件中的所有sheet，提取元数据和样例数据
"""

import pandas as pd
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass, field

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


@dataclass
class SheetState:
    """单个Sheet的状态"""
    name: str                              # Sheet名称
    original_df: pd.DataFrame              # 原始DataFrame（只读）
    current_df: pd.DataFrame               # 当前DataFrame（可修改）
    metadata: Dict[str, Any]               # 元数据
    modification_count: int = 0            # 修改次数
    last_modified_iteration: int = 0       # 最后修改的迭代轮次
    
    def get_summary(self) -> str:
        """获取状态摘要"""
        summary = f"Sheet '{self.name}': {self.current_df.shape[0]} rows × {self.current_df.shape[1]} cols"
        if self.modification_count > 0:
            summary += f" (modified {self.modification_count} times)"
        return summary


@dataclass
class MultiSheetContext:
    """多Sheet上下文"""
    file_path: str
    sheet_states: Dict[str, SheetState] = field(default_factory=dict)
    default_sheet: str = ""
    total_sheets: int = 0
    
    def get_sheet_names(self) -> List[str]:
        """获取所有sheet名称"""
        return list(self.sheet_states.keys())
    
    def get_current_df(self, sheet_name: str) -> pd.DataFrame:
        """获取指定sheet的当前DataFrame"""
        if sheet_name not in self.sheet_states:
            raise ValueError(f"Sheet '{sheet_name}' not found. Available: {self.get_sheet_names()}")
        return self.sheet_states[sheet_name].current_df
    
    def get_original_df(self, sheet_name: str) -> pd.DataFrame:
        """获取指定sheet的原始DataFrame"""
        if sheet_name not in self.sheet_states:
            raise ValueError(f"Sheet '{sheet_name}' not found. Available: {self.get_sheet_names()}")
        return self.sheet_states[sheet_name].original_df
    
    def get_state(self, sheet_name: str) -> SheetState:
        """获取指定sheet的状态对象"""
        if sheet_name not in self.sheet_states:
            raise ValueError(f"Sheet '{sheet_name}' not found. Available: {self.get_sheet_names()}")
        return self.sheet_states[sheet_name]
    
    def update_sheet(self, sheet_name: str, df: pd.DataFrame, iteration: int = 0):
        """更新指定sheet的DataFrame"""
        if sheet_name not in self.sheet_states:
            raise ValueError(f"Sheet '{sheet_name}' not found. Available: {self.get_sheet_names()}")
        
        state = self.sheet_states[sheet_name]
        state.current_df = df
        state.modification_count += 1
        state.last_modified_iteration = iteration
    
    def get_all_states_summary(self) -> str:
        """获取所有sheet的状态摘要"""
        lines = []
        lines.append(f"Total Sheets: {self.total_sheets}")
        lines.append(f"Default Sheet: {self.default_sheet}")
        lines.append("\nSheet States:")
        for name, state in self.sheet_states.items():
            prefix = "→" if name == self.default_sheet else " "
            lines.append(f"  {prefix} {state.get_summary()}")
        return "\n".join(lines)


class MultiSheetLoader:
    """多Sheet表格加载器"""
    
    def __init__(self, max_preview_rows: int = 10, max_sheets: int = 20):
        """
        初始化加载器
        
        Args:
            max_preview_rows: 预览数据的最大行数
            max_sheets: 最多加载的sheet数量
        """
        if not HAS_OPENPYXL:
            raise ImportError("openpyxl is required. Install: pip install openpyxl")
        
        self.max_preview_rows = max_preview_rows
        self.max_sheets = max_sheets
    
    def load_excel_file(
        self, 
        file_path: str,
        processor=None,
        meta_extractor=None
    ) -> MultiSheetContext:
        """
        加载Excel文件的所有sheet
        
        Args:
            file_path: Excel文件路径
            processor: SmartTableProcessor实例（可选）
            meta_extractor: MetaExtractor实例（可选）
            
        Returns:
            MultiSheetContext对象
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        if file_path.suffix.lower() not in ['.xlsx', '.xls']:
            raise ValueError(f"Only Excel files are supported, got: {file_path.suffix}")
        
        # 1. 获取所有sheet名称
        sheet_names = self._get_sheet_names(file_path)
        
        if len(sheet_names) == 0:
            raise ValueError(f"No sheets found in file: {file_path}")
        
        # 限制sheet数量
        if len(sheet_names) > self.max_sheets:
            print(f"⚠️  Warning: File has {len(sheet_names)} sheets, loading first {self.max_sheets}")
            sheet_names = sheet_names[:self.max_sheets]
        
        # 2. 加载所有sheet
        sheet_states = {}
        for sheet_name in sheet_names:
            df, metadata = self._load_single_sheet(
                file_path, 
                sheet_name,
                processor=processor,
                meta_extractor=meta_extractor
            )
            
            # 创建SheetState
            state = SheetState(
                name=sheet_name,
                original_df=df.copy(),
                current_df=df.copy(),
                metadata=metadata
            )
            sheet_states[sheet_name] = state
        
        # 3. 创建MultiSheetContext
        context = MultiSheetContext(
            file_path=str(file_path),
            sheet_states=sheet_states,
            default_sheet=sheet_names[0],  # 第一个sheet作为默认
            total_sheets=len(sheet_names)
        )
        
        return context
    
    def _get_sheet_names(self, file_path: Path) -> List[str]:
        """获取所有sheet名称"""
        try:
            workbook = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
            sheet_names = workbook.sheetnames
            workbook.close()
            return sheet_names
        except Exception as e:
            print(f"⚠️  Warning: Failed to read sheet names with openpyxl: {e}")
            # Fallback: 使用pandas
            try:
                xl_file = pd.ExcelFile(file_path)
                return xl_file.sheet_names
            except Exception as e2:
                raise ValueError(f"Failed to read Excel file: {e2}")
    
    def _load_single_sheet(
        self,
        file_path: Path,
        sheet_name: str,
        processor=None,
        meta_extractor=None
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """
        加载单个sheet
        
        Returns:
            (dataframe, metadata)
        """
        try:
            # 如果有processor，使用它处理（支持复杂表格）
            if processor:
                try:
                    df, proc_metadata = processor.process_excel(
                        str(file_path),
                        sheet_name=sheet_name
                    )
                except Exception as e:
                    # Fallback: 直接用pandas加载
                    print(f"⚠️  Warning: SmartTableProcessor failed for sheet '{sheet_name}': {e}")
                    df = pd.read_excel(file_path, sheet_name=sheet_name)
                    proc_metadata = {}
            else:
                # 直接用pandas加载
                df = pd.read_excel(file_path, sheet_name=sheet_name)
                proc_metadata = {}
            
            # 提取元数据
            if meta_extractor:
                try:
                    meta_info = meta_extractor.extract_meta_info(
                        str(file_path),
                        sheet_name=sheet_name
                    )
                except Exception as e:
                    print(f"⚠️  Warning: MetaExtractor failed for sheet '{sheet_name}': {e}")
                    meta_info = {}
            else:
                meta_info = {}
            
            # 合并metadata
            metadata = {
                "sheet_name": sheet_name,
                "shape": df.shape,
                "columns": list(df.columns),
                "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
                "processor_metadata": proc_metadata,
                "meta_info": meta_info
            }
            
            return df, metadata
            
        except Exception as e:
            raise ValueError(f"Failed to load sheet '{sheet_name}': {e}")
    
    def generate_sheets_overview(
        self, 
        context: MultiSheetContext,
        include_preview: bool = True
    ) -> str:
        """
        生成所有sheet的概览信息（用于prompt）
        
        Args:
            context: MultiSheetContext对象
            include_preview: 是否包含数据预览
            
        Returns:
            格式化的概览文本
        """
        lines = []
        
        lines.append(f"## 📊 Available Sheets ({context.total_sheets} total)")
        lines.append("")
        
        for idx, (sheet_name, state) in enumerate(context.sheet_states.items(), 1):
            df = state.current_df
            is_default = (sheet_name == context.default_sheet)
            
            # Sheet标题
            default_marker = " ⭐ (default)" if is_default else ""
            lines.append(f"### {idx}. **{sheet_name}**{default_marker}")
            lines.append("")
            
            # 基本信息
            lines.append(f"- **Shape**: {df.shape[0]} rows × {df.shape[1]} columns")
            
            # 列名（最多显示前15个）
            col_preview = list(df.columns[:15])
            if len(df.columns) > 15:
                col_preview_str = ", ".join(col_preview) + f", ... ({len(df.columns) - 15} more)"
            else:
                col_preview_str = ", ".join(col_preview)
            lines.append(f"- **Columns**: {col_preview_str}")
            
            # 数据预览
            if include_preview and not df.empty:
                lines.append("")
                preview_rows = min(self.max_preview_rows, len(df))
                lines.append(f"**Data Preview** (first {preview_rows} rows):")
                lines.append("```")
                lines.append(df.head(preview_rows).to_string())
                lines.append("```")
            
            lines.append("")
        
        return "\n".join(lines)
    
    def generate_sheet_selection_guide(self) -> str:
        """生成sheet选择的使用指南（用于prompt）"""
        guide = """## 🎯 How to Select a Sheet

To operate on a specific sheet, specify the `sheet_name` variable in your code:

```python
# Example 1: Work with a specific sheet
sheet_name = 'Sales Data'  # Specify target sheet
df = df[df['Year'] > 2020]  # Operate on 'Sales Data' sheet
```

```python
# Example 2: Access other sheets (read-only)
sheet_name = 'Summary'  # Target sheet
# You can reference other sheets via the 'sheets' dict
sales_df = sheets['Sales Data']  # Read-only access to other sheets
df = pd.merge(df, sales_df, on='ID')
```

**Important Rules**:
1. If you don't specify `sheet_name`, the default sheet (first one) will be used
2. The `df` variable always refers to the target sheet's DataFrame
3. Use `sheets[name]` to access other sheets in read-only mode
4. All modifications to `df` are saved and persist across iterations
5. You can switch between sheets in different iterations

**Example of multi-sheet workflow**:
```python
# Iteration 1: Process Sheet1
sheet_name = 'Sheet1'
df = df.groupby('Category')['Value'].sum().reset_index()

# Iteration 2: Process Sheet2
sheet_name = 'Sheet2'
df = df[df['Year'] == 2023]

# Iteration 3: Combine results from both sheets
sheet_name = 'Sheet1'  # Back to Sheet1
sheet2_data = sheets['Sheet2']  # Reference Sheet2
df = pd.merge(df, sheet2_data, on='Category')
```
"""
        return guide


# 便捷函数
def load_excel_with_multi_sheet_support(
    file_path: str,
    processor=None,
    meta_extractor=None,
    max_preview_rows: int = 10
) -> MultiSheetContext:
    """
    便捷函数：加载Excel文件（支持多sheet）
    
    Args:
        file_path: Excel文件路径
        processor: SmartTableProcessor实例（可选）
        meta_extractor: MetaExtractor实例（可选）
        max_preview_rows: 预览行数
        
    Returns:
        MultiSheetContext对象
    """
    loader = MultiSheetLoader(max_preview_rows=max_preview_rows)
    return loader.load_excel_file(file_path, processor=processor, meta_extractor=meta_extractor)


if __name__ == "__main__":
    # 测试代码
    print("MultiSheetLoader module loaded successfully")
