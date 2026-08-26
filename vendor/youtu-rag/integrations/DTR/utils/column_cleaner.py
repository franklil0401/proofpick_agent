"""
Column Name Cleaner
清理和规范化DataFrame的列名，便于LLM理解和使用
"""

import pandas as pd
import re
from typing import Dict, List, Tuple


class ColumnCleaner:
    """清理和规范化列名"""
    
    def __init__(self):
        pass
    
    def _extract_keywords(self, col_name: str) -> str:
        """从复杂列名中提取关键词"""
        # 移除换行符和多余空格
        clean = str(col_name).replace('\n', ' ').replace('\r', ' ')
        clean = ' '.join(clean.split())
        
        # 关键词模式匹配
        keywords_patterns = [
            (r'(?i)(year|年份|年度)', 'Year'),
            (r'(?i)(agriculture|农业|agri)', 'Agriculture'),
            (r'(?i)(employed|employment|就业)', 'Employed'),
            (r'(?i)(unemployed|失业)', 'Unemployed'),
            (r'(?i)(population|人口)', 'Population'),
            (r'(?i)(labor\s*force|劳动力)', 'LaborForce'),
            (r'(?i)(total|总计|合计)', 'Total'),
            (r'(?i)(percent|percentage|百分比|%)', 'Percent'),
            (r'(?i)(civilian|民用|平民)', 'Civilian'),
            (r'(?i)(nonagricultur|非农)', 'Nonagricultural'),
            (r'(?i)(industri|工业)', 'Industry'),
            (r'(?i)(not.*labor.*force|非劳动力)', 'NotInLaborForce'),
            (r'(?i)(number|数量)', 'Number'),
            (r'(?i)(rate|比率)', 'Rate'),
        ]
        
        # 尝试匹配关键词
        for pattern, keyword in keywords_patterns:
            if re.search(pattern, clean):
                return keyword
        
        # 如果没有匹配，提取前3个有意义的单词
        words = [w for w in clean.split() if len(w) > 2 and not w.startswith('[')]
        if words:
            return '_'.join(words[:3])[:30]
        
        return 'Column'
    
    def clean_columns(self, df: pd.DataFrame, strategy: str = 'smart') -> Tuple[pd.DataFrame, Dict[str, str]]:
        """清理DataFrame的列名
        
        Args:
            df: 原始DataFrame
            strategy: 清理策略
                - 'smart': 智能提取关键词
                - 'simple': 简单编号（Col_0, Col_1, ...）
                - 'truncate': 截断长列名
        
        Returns:
            (cleaned_df, column_mapping)
            - cleaned_df: 列名已清理的DataFrame
            - column_mapping: {new_name: old_name} 映射字典
        """
        df_copy = df.copy()
        old_columns = list(df.columns)
        column_mapping = {}
        
        if strategy == 'smart':
            new_columns = []
            seen_names = {}
            
            for col in old_columns:
                # 提取关键词
                base_name = self._extract_keywords(col)
                
                # 处理重复名称
                if base_name in seen_names:
                    seen_names[base_name] += 1
                    new_name = f"{base_name}_{seen_names[base_name]}"
                else:
                    seen_names[base_name] = 0
                    new_name = base_name
                
                new_columns.append(new_name)
                column_mapping[new_name] = col
            
            df_copy.columns = new_columns
            
        elif strategy == 'simple':
            new_columns = [f"Col_{i}" for i in range(len(old_columns))]
            column_mapping = {new: old for new, old in zip(new_columns, old_columns)}
            df_copy.columns = new_columns
            
        elif strategy == 'truncate':
            new_columns = []
            for col in old_columns:
                clean = str(col).replace('\n', ' ').replace('\r', ' ')
                clean = ' '.join(clean.split())
                truncated = clean[:30] if len(clean) > 30 else clean
                new_columns.append(truncated)
            
            column_mapping = {new: old for new, old in zip(new_columns, old_columns)}
            df_copy.columns = new_columns
        
        return df_copy, column_mapping
    
    def format_mapping_for_prompt(self, column_mapping: Dict[str, str], max_display: int = 20) -> str:
        """将列名映射格式化为prompt的一部分
        
        Args:
            column_mapping: {new_name: old_name} 映射
            max_display: 最多显示多少个映射
        
        Returns:
            格式化的映射文本
        """
        lines = []
        lines.append("## Column Name Mapping (IMPORTANT - Use these clean names!):")
        lines.append("For easier coding, column names have been cleaned. Use the clean names below:")
        lines.append("")
        
        items = list(column_mapping.items())[:max_display]
        for new_name, old_name in items:
            # 截断过长的原始名称
            old_display = old_name if len(str(old_name)) <= 60 else str(old_name)[:57] + "..."
            lines.append(f"  - **{new_name}**: {old_display}")
        
        if len(column_mapping) > max_display:
            lines.append(f"  ... (and {len(column_mapping) - max_display} more columns)")
        
        lines.append("")
        lines.append("⚠️  Use ONLY the clean names (bold) in your code, not the original names!")
        
        return "\n".join(lines)


# 测试函数
def main():
    """测试列名清理功能"""
    import pandas as pd
    
    # 创建测试DataFrame
    test_df = pd.DataFrame({
        'HOUSEHOLD DATA\nANNUAL AVERAGES\n 1.  Employment status': [1, 2, 3],
        'Unnamed: 1': [4, 5, 6],
        'Year': [2020, 2021, 2022],
        'Agri-\nculture': [100, 200, 300],
        'Nonagri-\ncultural industries': [1000, 2000, 3000]
    })
    
    print("Original columns:")
    print(test_df.columns.tolist())
    print()
    
    cleaner = ColumnCleaner()
    cleaned_df, mapping = cleaner.clean_columns(test_df, strategy='smart')
    
    print("Cleaned columns:")
    print(cleaned_df.columns.tolist())
    print()
    
    print("Mapping:")
    print(cleaner.format_mapping_for_prompt(mapping))
    print()
    
    print("Cleaned DataFrame:")
    print(cleaned_df)


if __name__ == "__main__":
    main()

