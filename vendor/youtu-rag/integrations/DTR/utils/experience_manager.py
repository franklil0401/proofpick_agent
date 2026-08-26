"""
Experience Manager - 管理MCTS和SMG的经验持久化
"""

import json
import hashlib
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import shutil


class ExperienceManager:
    """
    经验管理器 - 持久化和复用MCTS/SMG经验
    
    存储结构：
    storage/
    ├── mcts_priors.json      # MCTS路径先验概率
    ├── smg_memory.json       # SMG执行记录
    └── code_cache.json       # 成功代码缓存
    """
    
    def __init__(self, storage_dir: str = "storage"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        # 文件路径
        self.mcts_file = self.storage_dir / "mcts_priors.json"
        self.smg_file = self.storage_dir / "smg_memory.json"
        self.code_cache_file = self.storage_dir / "code_cache.json"
        
        # 内存缓存
        self.mcts_priors = {}  # {path_signature: {count, success_count, avg_reward, prior}}
        self.smg_records = []  # [{operator, code, success, reward, timestamp}]
        self.code_cache = {}   # {cache_key: {code, success_rate, last_used}}
        
        # 加载现有数据
        self.load()
    
    def load(self):
        """从磁盘加载经验"""
        
        loaded_count = 0
        
        # 加载MCTS priors
        if self.mcts_file.exists():
            try:
                with open(self.mcts_file, 'r') as f:
                    self.mcts_priors = json.load(f)
                loaded_count += len(self.mcts_priors)
            except Exception as e:
                print(f"⚠️  Failed to load MCTS priors: {e}")
        
        # 加载SMG记录
        if self.smg_file.exists():
            try:
                with open(self.smg_file, 'r') as f:
                    data = json.load(f)
                    self.smg_records = data.get('records', [])
                loaded_count += len(self.smg_records)
            except Exception as e:
                print(f"⚠️  Failed to load SMG memory: {e}")
        
        # 加载代码缓存
        if self.code_cache_file.exists():
            try:
                with open(self.code_cache_file, 'r') as f:
                    self.code_cache = json.load(f)
                loaded_count += len(self.code_cache)
            except Exception as e:
                print(f"⚠️  Failed to load code cache: {e}")
        
        if loaded_count > 0:
            print(f"✓ Loaded {loaded_count} experience records from {self.storage_dir}")
    
    def save(self):
        """保存到磁盘"""
        
        try:
            # 保存MCTS priors
            with open(self.mcts_file, 'w') as f:
                json.dump(self.mcts_priors, f, indent=2)
            
            # 保存SMG记录
            with open(self.smg_file, 'w') as f:
                json.dump({
                    'last_updated': datetime.now().isoformat(),
                    'total_records': len(self.smg_records),
                    'records': self.smg_records[-1000:]  # 只保留最近1000条
                }, f, indent=2)
            
            # 保存代码缓存
            with open(self.code_cache_file, 'w') as f:
                json.dump(self.code_cache, f, indent=2)
            
            print(f"✓ Saved experience to {self.storage_dir} (MCTS: {len(self.mcts_priors)}, SMG: {len(self.smg_records)}, Cache: {len(self.code_cache)})")
            
        except Exception as e:
            print(f"⚠️  Failed to save experience: {e}")
    
    # ==================== MCTS Priors ====================
    
    def update_mcts_prior(self, path_operators: List[str], success: bool, reward: float):
        """
        更新MCTS路径先验
        
        Args:
            path_operators: ['FILTER_ROWS', 'SORT_VALUES', ...]
            success: 路径是否成功
            reward: 累计奖励
        """
        
        # 生成路径签名
        path_sig = "->".join(path_operators)
        
        if path_sig not in self.mcts_priors:
            self.mcts_priors[path_sig] = {
                'count': 0,
                'success_count': 0,
                'total_reward': 0.0,
                'prior': 0.5  # 初始先验
            }
        
        prior_data = self.mcts_priors[path_sig]
        prior_data['count'] += 1
        if success:
            prior_data['success_count'] += 1
        prior_data['total_reward'] += reward
        
        # 更新先验概率：综合成功率和平均奖励
        success_rate = prior_data['success_count'] / prior_data['count']
        avg_reward = prior_data['total_reward'] / prior_data['count']
        normalized_reward = min(1.0, max(0.0, avg_reward / 30.0))  # 假设max_reward=30
        
        # 先验 = 0.7 * 成功率 + 0.3 * 归一化奖励
        prior_data['prior'] = 0.7 * success_rate + 0.3 * normalized_reward
    
    def get_mcts_prior(self, path_operators: List[str]) -> float:
        """获取路径先验概率"""
        
        path_sig = "->".join(path_operators)
        if path_sig in self.mcts_priors:
            return self.mcts_priors[path_sig]['prior']
        
        return 0.5  # 未见过的路径返回默认先验
    
    def get_top_mcts_paths(self, top_k: int = 5) -> List[Dict]:
        """获取历史最佳路径"""
        
        items = []
        for path_sig, data in self.mcts_priors.items():
            items.append({
                'path': path_sig,
                'operators': path_sig.split('->'),
                'prior': data['prior'],
                'success_rate': data['success_count'] / data['count'] if data['count'] > 0 else 0,
                'count': data['count']
            })
        
        items.sort(key=lambda x: x['prior'], reverse=True)
        return items[:top_k]
    
    # ==================== SMG Memory ====================
    
    def add_smg_record(
        self,
        operator: str,
        code: str,
        success: bool,
        reward: Dict[str, float],
        error: Optional[str] = None
    ):
        """
        添加SMG执行记录
        
        Args:
            operator: 操作符名称
            code: 生成的代码
            success: 是否成功
            reward: 奖励向量
            error: 错误信息（如果失败）
        """
        
        record = {
            'operator': operator,
            'code': code[:500],  # 只保留前500字符
            'success': success,
            'reward': reward,
            'error': error[:200] if error else None,
            'timestamp': datetime.now().isoformat()
        }
        
        self.smg_records.append(record)
    
    def get_smg_success_examples(self, operator: str, limit: int = 3) -> List[Dict]:
        """获取某个operator的成功案例"""
        
        examples = [
            rec for rec in self.smg_records
            if rec['operator'] == operator and rec['success']
        ]
        
        # 按时间倒序，返回最近的
        examples.sort(key=lambda x: x['timestamp'], reverse=True)
        return examples[:limit]
    
    def get_smg_failure_patterns(self, operator: str, limit: int = 2) -> List[Dict]:
        """获取某个operator的失败模式"""
        
        failures = [
            rec for rec in self.smg_records
            if rec['operator'] == operator and not rec['success']
        ]
        
        # 按时间倒序
        failures.sort(key=lambda x: x['timestamp'], reverse=True)
        return failures[:limit]
    
    # ==================== Code Cache ====================
    
    def get_cached_code(self, operator: str, df_signature: str) -> Optional[str]:
        """
        从缓存获取代码
        
        Args:
            operator: 操作符名称
            df_signature: DataFrame签名（shape + columns的hash）
        
        Returns:
            缓存的代码，如果不存在返回None
        """
        
        cache_key = f"{operator}:{df_signature}"
        
        if cache_key in self.code_cache:
            cache_entry = self.code_cache[cache_key]
            # 更新最后使用时间
            cache_entry['last_used'] = datetime.now().isoformat()
            cache_entry['hits'] = cache_entry.get('hits', 0) + 1
            return cache_entry['code']
        
        return None
    
    def cache_code(
        self,
        operator: str,
        df_signature: str,
        code: str,
        success: bool
    ):
        """缓存代码（只缓存成功的）"""
        
        if not success:
            return
        
        cache_key = f"{operator}:{df_signature}"
        
        self.code_cache[cache_key] = {
            'code': code,
            'operator': operator,
            'success': True,
            'cached_at': datetime.now().isoformat(),
            'last_used': datetime.now().isoformat(),
            'hits': 0
        }
        
        # 限制缓存大小
        if len(self.code_cache) > 1000:
            self._trim_code_cache()
    
    def _trim_code_cache(self):
        """修剪代码缓存（保留最常用的）"""
        
        items = list(self.code_cache.items())
        items.sort(key=lambda x: x[1].get('hits', 0), reverse=True)
        
        # 保留前800个
        self.code_cache = {k: v for k, v in items[:800]}
    
    # ==================== 统计信息 ====================
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        
        # MCTS统计
        mcts_total = len(self.mcts_priors)
        mcts_avg_prior = sum(p['prior'] for p in self.mcts_priors.values()) / mcts_total if mcts_total > 0 else 0
        
        # SMG统计
        smg_total = len(self.smg_records)
        smg_success = sum(1 for r in self.smg_records if r['success'])
        smg_success_rate = smg_success / smg_total if smg_total > 0 else 0
        
        # 代码缓存统计
        cache_total = len(self.code_cache)
        cache_total_hits = sum(c.get('hits', 0) for c in self.code_cache.values())
        
        return {
            'mcts': {
                'total_paths': mcts_total,
                'avg_prior': mcts_avg_prior
            },
            'smg': {
                'total_records': smg_total,
                'success_count': smg_success,
                'success_rate': smg_success_rate
            },
            'cache': {
                'total_entries': cache_total,
                'total_hits': cache_total_hits,
                'avg_hits': cache_total_hits / cache_total if cache_total > 0 else 0
            }
        }
    
    def print_stats(self):
        """打印统计信息"""
        
        stats = self.get_stats()
        
        print(f"\n{'='*70}")
        print("📊 EXPERIENCE STATISTICS")
        print(f"{'='*70}")
        
        print(f"\nMCTS Priors:")
        print(f"  Total Paths: {stats['mcts']['total_paths']}")
        print(f"  Avg Prior: {stats['mcts']['avg_prior']:.3f}")
        
        print(f"\nSMG Memory:")
        print(f"  Total Records: {stats['smg']['total_records']}")
        print(f"  Success Rate: {stats['smg']['success_rate']*100:.1f}%")
        
        print(f"\nCode Cache:")
        print(f"  Total Entries: {stats['cache']['total_entries']}")
        print(f"  Total Hits: {stats['cache']['total_hits']}")
        print(f"  Avg Hits/Entry: {stats['cache']['avg_hits']:.1f}")
        
        print(f"\n{'='*70}\n")
    
    def clear_all(self):
        """清空所有经验"""
        
        self.mcts_priors = {}
        self.smg_records = []
        self.code_cache = {}
        
        # 删除文件
        for f in [self.mcts_file, self.smg_file, self.code_cache_file]:
            if f.exists():
                f.unlink()
        
        print("✓ Cleared all experience data")
    
    def backup(self, backup_dir: str = "storage_backup"):
        """备份经验数据"""
        
        backup_path = Path(backup_dir)
        backup_path.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_subdir = backup_path / f"backup_{timestamp}"
        
        shutil.copytree(self.storage_dir, backup_subdir)
        
        print(f"✓ Backed up experience to {backup_subdir}")


# 测试
if __name__ == "__main__":
    manager = ExperienceManager()
    
    # 添加测试数据
    manager.update_mcts_prior(['FILTER', 'SORT'], True, 25.0)
    manager.update_mcts_prior(['FILTER', 'SORT'], True, 28.0)
    manager.update_mcts_prior(['GROUP', 'AGG'], False, 5.0)
    
    manager.add_smg_record(
        operator='FILTER_ROWS',
        code='df = df[df["Year"] > 2000]',
        success=True,
        reward={'execution_success': 1.0}
    )
    
    manager.save()
    manager.print_stats()

