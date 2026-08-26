"""
Schema Linking Module - 统一的表头智能选择模块

PURPOSE:
- 根据问题智能选择相关的行列表头
- 生成过滤后的Markdown表格
- 提供Schema信息给其他模块使用
- 减少无关信息干扰，提高LLM理解准确性

USAGE:
    schema_linker = SchemaLinkingModule(llm_client)
    result = schema_linker.link_schema(question, meta_graph)
    # result包含：
    # - selected_row_headers: 相关行表头
    # - selected_col_headers: 相关列表头
    # - filtered_markdown_table: 过滤后的表格
    # - triplets: 三元组信息
"""

import json
import re
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SchemaLinkingResult:
    """Schema Linking结果"""
    selected_row_headers: List[str]
    selected_col_headers: List[str]
    triplets: List[str]
    filtered_markdown_table: str
    full_markdown_table: str  # 保留完整表格，用于fallback
    confidence: float = 0.0


class SchemaLinkingModule:
    """统一的Schema Linking模块，供所有组件使用"""
    
    def __init__(self, llm_client):
        self.llm_client = llm_client
        self._meta_markdown_cache = {}  # 缓存meta转markdown的结果
    
    def link_schema(
        self, 
        question: str, 
        meta_graph: Dict,
        expand_range: bool = False,
        max_retries: int = 1
    ) -> SchemaLinkingResult:
        """执行Schema Linking
        
        Args:
            question: 问题
            meta_graph: 元图
            expand_range: 是否扩大选择范围（用于迭代反思）
            max_retries: 最大重试次数
        
        Returns:
            SchemaLinkingResult包含选中的表头和过滤后的表格
        """
        # 1. 提取三元组
        triplets = self._extract_triplets_from_meta(meta_graph)
        
        if not triplets:
            # 如果没有三元组，返回完整表格
            full_table = self._meta_to_markdown(meta_graph)
            return SchemaLinkingResult(
                selected_row_headers=[],
                selected_col_headers=[],
                triplets=[],
                filtered_markdown_table=full_table,
                full_markdown_table=full_table,
                confidence=0.0
            )
        
        # 2. 构建prompt并调用LLM
        for attempt in range(max_retries + 1):
            prompt = self._build_schema_linking_prompt(
                question, triplets, expand_range, attempt
            )
            
            response = self.llm_client.call_api(prompt)
            parsed = self._parse_json_safely(response)
            
            if parsed:
                break
        else:
            # 解析失败，返回完整表格
            parsed = {"selected_row_headers": [], "selected_col_headers": []}
        
        # 3. 解析结果
        selected_rows = parsed.get("selected_row_headers", [])
        selected_cols = parsed.get("selected_col_headers", [])
        
        # 确保是列表
        if not isinstance(selected_rows, list):
            selected_rows = []
        if not isinstance(selected_cols, list):
            selected_cols = []
        
        # 4. 生成markdown表格
        full_table = self._meta_to_markdown(meta_graph)
        
        # 5. 过滤表格（根据选中的表头）
        if selected_rows or selected_cols:
            filtered_table = self._filter_table_by_headers(
                full_table, selected_rows, selected_cols
            )
        else:
            # 如果没有选中任何表头，返回完整表格
            filtered_table = full_table
        
        # 6. 提取相关三元组
        relevant_triplets = self._filter_triplets(
            triplets, selected_rows, selected_cols
        )
        
        # 7. 计算置信度
        confidence = 1.0 if (selected_rows or selected_cols) else 0.5
        
        return SchemaLinkingResult(
            selected_row_headers=selected_rows,
            selected_col_headers=selected_cols,
            triplets=relevant_triplets,
            filtered_markdown_table=filtered_table,
            full_markdown_table=full_table,
            confidence=confidence
        )
    
    def _extract_triplets_from_meta(self, meta_graph: Dict) -> List[str]:
        """从meta graph提取三元组
        
        提取的三元组类型：
        1. (table, has_column_header, "header_value")
        2. (table, has_row_header, "header_value")
        3. ("parent_header", has_child, "child_header")
        """
        triplets = []
        entities = meta_graph.get("entities", [])
        relationships = meta_graph.get("relationships", [])
        
        if not entities:
            return []
        
        # 构建实体映射
        entity_map = {ent.get("id"): ent for ent in entities}
        
        # 收集列标题和行标题
        col_headers = []
        row_headers = []
        
        for ent in entities:
            label = ent.get("label", "")
            props = ent.get("properties", {}) or {}
            
            if label == "column_header":
                value = props.get("value") or props.get("value_text") or props.get("value_norm") or props.get("text")
                if value and isinstance(value, str) and value.strip() and not value.strip().startswith('[EMPTY_'):
                    col_headers.append((ent.get("id"), value.strip()))
            elif label == "row_header":
                value = props.get("value") or props.get("value_text") or props.get("value_norm") or props.get("text")
                if value and isinstance(value, str) and value.strip() and not value.strip().startswith('[EMPTY_'):
                    row_headers.append((ent.get("id"), value.strip()))
        
        # 生成表头三元组（限制数量）
        for header_id, value in col_headers[:30]:
            value_clean = value.replace('\n', ' ').replace('  ', ' ')[:80]
            triplets.append(f'(table, has_column_header, "{value_clean}")')
        
        for header_id, value in row_headers[:30]:
            value_clean = value.replace('\n', ' ').replace('  ', ' ')[:80]
            triplets.append(f'(table, has_row_header, "{value_clean}")')
        
        # 生成层级关系三元组
        hierarchy_count = 0
        for rel in relationships:
            if hierarchy_count >= 20:  # 限制层级关系数量
                break
            
            if rel.get("relation") == "has_child":
                start_id = rel.get("start_entity_id")
                end_id = rel.get("end_entity_id")
                
                start_ent = entity_map.get(start_id)
                end_ent = entity_map.get(end_id)
                
                if start_ent and end_ent:
                    start_val = self._get_entity_value(start_ent)
                    end_val = self._get_entity_value(end_ent)
                    
                    if start_val and end_val:
                        # 检查level（只保留level <= 2的）
                        start_props = start_ent.get("properties", {}) or {}
                        end_props = end_ent.get("properties", {}) or {}
                        start_level = start_props.get("level", 0)
                        end_level = end_props.get("level", 0)
                        
                        if start_level <= 2 and end_level <= 2:
                            start_val_clean = start_val.replace('\n', ' ')[:80]
                            end_val_clean = end_val.replace('\n', ' ')[:80]
                            triplets.append(f'("{start_val_clean}", has_child, "{end_val_clean}")')
                            hierarchy_count += 1
        
        return triplets
    
    def _build_schema_linking_prompt(
        self, 
        question: str, 
        triplets: List[str],
        expand_range: bool,
        attempt: int
    ) -> str:
        """构建Schema Linking prompt"""
        
        expansion_hint = ""
        if expand_range:
            expansion_hint = "\n\n**注意**：这是扩展范围的查询，请选择更多相关的表头（比之前更宽泛）。"
        
        retry_hint = ""
        if attempt > 0:
            retry_hint = "\n\n**重要**：请确保输出有效的JSON格式。"
        
        # 限制三元组数量以控制token
        display_triplets = triplets[:50]
        
        prompt = f"""你是表格分析专家。请根据问题选择相关的表头。

# 问题
{question}{expansion_hint}

# 表格结构信息（三元组形式）
{chr(10).join(display_triplets)}

# 任务
根据问题判断需要用到哪些表头（行表头和列表头）来回答问题。

# 输出要求
严格输出JSON格式：
{{
  "selected_row_headers": ["header1", "header2"],
  "selected_col_headers": ["col1", "col2"]
}}

注意：
- 只选择与问题直接相关的表头
- 如果问题涉及所有行列，可以返回空列表
- selected_row_headers: 从 has_row_header 三元组中选择
- selected_col_headers: 从 has_column_header 三元组中选择
{retry_hint}

请输出JSON：
"""
        return prompt
    
    def _meta_to_markdown(self, meta_graph: Dict) -> str:
        """将meta graph转为markdown表格（带缓存）"""
        # 使用meta_graph的hash作为缓存key
        cache_key = str(id(meta_graph))
        
        if cache_key in self._meta_markdown_cache:
            return self._meta_markdown_cache[cache_key]
        
        # 使用现有的转换逻辑
        try:
            # 尝试导入baseline的转换函数
            from baselines.Meta_Markdown import MetaMarkdownBaseline
            baseline = MetaMarkdownBaseline()
            markdown_table = baseline._convert_to_markdown_table(meta_graph)
        except Exception as e:
            # 如果导入失败，使用简化版本
            markdown_table = self._simple_meta_to_markdown(meta_graph)
        
        # 缓存结果
        self._meta_markdown_cache[cache_key] = markdown_table
        return markdown_table
    
    def _simple_meta_to_markdown(self, meta_graph: Dict) -> str:
        """简化版的meta转markdown（fallback）"""
        entities = meta_graph.get("entities", [])
        
        # 收集列标题和数据单元格
        col_headers = {}
        data_cells = {}
        
        for ent in entities:
            label = ent.get("label", "")
            props = ent.get("properties", {}) or {}
            
            if label == "column_header":
                col = props.get("col")
                value = props.get("value") or props.get("text", "")
                if col is not None:
                    col_headers[col] = str(value)
            elif label == "data_cell":
                row = props.get("row")
                col = props.get("col")
                value = props.get("value") or props.get("text", "")
                if row is not None and col is not None:
                    if row not in data_cells:
                        data_cells[row] = {}
                    data_cells[row][col] = str(value)
        
        if not col_headers:
            return "# Empty Table\n"
        
        # 构建markdown表格
        lines = []
        max_col = max(col_headers.keys()) if col_headers else 0
        
        # 表头行
        header_row = []
        for col in range(max_col + 1):
            header_row.append(col_headers.get(col, ""))
        lines.append("| " + " | ".join(header_row) + " |")
        
        # 分隔行
        lines.append("|" + "|".join(["---"] * len(header_row)) + "|")
        
        # 数据行
        for row in sorted(data_cells.keys()):
            data_row = []
            for col in range(max_col + 1):
                data_row.append(data_cells[row].get(col, ""))
            lines.append("| " + " | ".join(data_row) + " |")
        
        return "\n".join(lines)
    
    def _filter_table_by_headers(
        self,
        markdown_table: str,
        selected_rows: List[str],
        selected_cols: List[str]
    ) -> str:
        """根据选中的headers过滤表格（模糊匹配）"""
        
        if not selected_rows and not selected_cols:
            return markdown_table
        
        lines = markdown_table.split('\n')
        result_lines = []
        
        # 解析markdown表格
        table_lines = []
        in_table = False
        header_line = None
        separator_line = None
        
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('|') and '|' in stripped[1:]:
                if not in_table:
                    in_table = True
                    header_line = line
                    table_lines.append(line)
                else:
                    # 检查是否是分隔行
                    if stripped.replace('|', '').replace('-', '').replace(' ', '').strip() == '':
                        separator_line = line
                        table_lines.append(line)
                    else:
                        table_lines.append(line)
            else:
                if in_table and stripped:
                    # 表格结束
                    break
                elif not in_table:
                    result_lines.append(line)
        
        if not table_lines or not header_line:
            return markdown_table
        
        # 解析表头
        header_cells = [cell.strip() for cell in header_line.split('|')[1:-1]]
        
        # 根据选中的列header，找到对应的列索引
        selected_col_indices = []
        if selected_cols:
            for col_idx, header_cell in enumerate(header_cells):
                # 模糊匹配
                for selected_header in selected_cols:
                    if self._fuzzy_match(selected_header, header_cell):
                        if col_idx not in selected_col_indices:
                            selected_col_indices.append(col_idx)
                        break
        else:
            # 如果没有指定列，使用全部列
            selected_col_indices = list(range(len(header_cells)))
        
        if not selected_col_indices:
            # 如果没有匹配到任何列，返回完整表格
            return markdown_table
        
        # 提取表头的选中列
        selected_header_cells = [header_cells[i] for i in selected_col_indices if i < len(header_cells)]
        if selected_header_cells:
            result_lines.append('| ' + ' | '.join(selected_header_cells) + ' |')
        
        # 提取分隔行
        if separator_line:
            result_lines.append('|' + '|'.join(['---'] * len(selected_header_cells)) + '|')
        
        # 提取数据行
        for line in table_lines[2:]:  # 跳过表头和分隔行
            stripped = line.strip()
            if not stripped.startswith('|'):
                continue
            
            cells = [cell.strip() for cell in line.split('|')[1:-1]]
            
            # 检查第一列（行标识符）是否匹配选中的行header
            if selected_rows and cells:
                first_cell = cells[0]
                matched = False
                for selected_header in selected_rows:
                    if self._fuzzy_match(selected_header, first_cell):
                        matched = True
                        break
                
                if not matched:
                    continue
            
            # 提取选中的列
            selected_cells = [cells[i] for i in selected_col_indices if i < len(cells)]
            
            if selected_cells:
                result_lines.append('| ' + ' | '.join(selected_cells) + ' |')
        
        return '\n'.join(result_lines)
    
    def _fuzzy_match(self, pattern: str, text: str) -> bool:
        """模糊匹配（不区分大小写，部分匹配）"""
        pattern_lower = pattern.lower()
        text_lower = text.lower()
        
        # 完全匹配
        if pattern_lower == text_lower:
            return True
        
        # 包含匹配
        if pattern_lower in text_lower or text_lower in pattern_lower:
            return True
        
        # 去除空格后匹配
        pattern_no_space = pattern_lower.replace(' ', '')
        text_no_space = text_lower.replace(' ', '')
        if pattern_no_space in text_no_space or text_no_space in pattern_no_space:
            return True
        
        return False
    
    def _filter_triplets(
        self,
        triplets: List[str],
        selected_rows: List[str],
        selected_cols: List[str]
    ) -> List[str]:
        """过滤三元组，只保留与选中表头相关的"""
        if not selected_rows and not selected_cols:
            return triplets[:30]  # 限制数量
        
        relevant = []
        
        for triplet in triplets:
            # 检查是否包含选中的表头
            is_relevant = False
            
            for selected_header in selected_rows + selected_cols:
                if selected_header.lower() in triplet.lower():
                    is_relevant = True
                    break
            
            if is_relevant:
                relevant.append(triplet)
        
        return relevant[:30]  # 限制数量
    
    def _parse_json_safely(self, text: str) -> Optional[Dict]:
        """安全解析JSON"""
        if not text:
            return None
        
        # 方法1: 直接解析
        try:
            return json.loads(text.strip())
        except:
            pass
        
        # 方法2: 提取第一个{}块
        try:
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1 and end > start:
                json_str = text[start:end+1]
                return json.loads(json_str)
        except:
            pass
        
        # 方法3: 使用正则提取
        try:
            match = re.search(r'\{[^{}]*"selected_row_headers"[^{}]*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group())
        except:
            pass
        
        return None
    
    def _get_entity_value(self, entity: Dict) -> Optional[str]:
        """获取实体的值"""
        props = entity.get("properties", {}) or {}
        value = props.get("value") or props.get("value_text") or props.get("value_norm") or props.get("text")
        if value and isinstance(value, str) and value.strip():
            return value.strip()
        return None
    
    def expand_schema(
        self,
        original_result: SchemaLinkingResult,
        question: str,
        meta_graph: Dict,
        additional_context: str = ""
    ) -> SchemaLinkingResult:
        """扩展Schema范围（用于迭代反思）
        
        Args:
            original_result: 原始的schema linking结果
            question: 问题
            meta_graph: 元图
            additional_context: 额外的上下文信息（如反思中发现的问题）
        """
        # 重新执行schema linking，带扩展标记
        enhanced_question = question
        if additional_context:
            enhanced_question = f"{question}\n\n额外需求: {additional_context}"
        
        return self.link_schema(
            enhanced_question,
            meta_graph,
            expand_range=True
        )
