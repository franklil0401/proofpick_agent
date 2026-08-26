"""
DTR Framework - Comprehensive Logging and Debugging

Provides detailed logging for all modules and execution replay capabilities.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
import logging


class DTRLogger:
    """
    Comprehensive logger for DTR framework.
    Logs all operations, code generation, rewards, and state changes.
    """
    
    def __init__(self, log_dir: str = "logs/dtr", enable_file_logging: bool = True):
        """
        Args:
            log_dir: Directory for log files
            enable_file_logging: Whether to save logs to files
        """
        self.log_dir = Path(log_dir)
        self.enable_file_logging = enable_file_logging
        
        if self.enable_file_logging:
            self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Create session ID
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Log storage
        self.session_log: List[Dict[str, Any]] = []
        self.operator_logs: List[Dict[str, Any]] = []
        self.reward_logs: List[Dict[str, Any]] = []
        self.path_logs: List[Dict[str, Any]] = []
        
        # Initialize Python logger
        self.logger = logging.getLogger(f"DTR_{self.session_id}")
        self.logger.setLevel(logging.INFO)
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'
        )
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
        
        # File handler
        if self.enable_file_logging:
            log_file = self.log_dir / f"session_{self.session_id}.log"
            file_handler = logging.FileHandler(log_file)
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
        
        self.logger.info(f"DTR Logger initialized (session: {self.session_id})")
    
    # Convenience methods to proxy to internal logger
    def info(self, message: str):
        """Log info message"""
        self.logger.info(message)
    
    def warning(self, message: str):
        """Log warning message"""
        self.logger.warning(message)
    
    def error(self, message: str):
        """Log error message"""
        self.logger.error(message)
    
    def debug(self, message: str):
        """Log debug message"""
        self.logger.debug(message)
    
    def log_ado_extraction(
        self,
        user_query: str,
        operators: List[Any],
        raw_response: str
    ):
        """Log ADO operator extraction"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "module": "ADO",
            "action": "extract_operators",
            "user_query": user_query,
            "operators_count": len(operators),
            "operators": [op.name for op in operators],
            "raw_response": raw_response[:500]  # Truncate for readability
        }
        
        self.operator_logs.append(log_entry)
        self.session_log.append(log_entry)
        
        self.logger.info(f"[ADO] Extracted {len(operators)} operators: {[op.name for op in operators]}")
    
    def log_mcts_planning(
        self,
        operators: List[str],
        paths_generated: int,
        top_paths: List[Any]
    ):
        """Log MCTS path planning"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "module": "MCTS",
            "action": "plan_paths",
            "input_operators": operators,
            "paths_generated": paths_generated,
            "top_paths": [
                {
                    "path_id": p.path_id,
                    "operators": p.operators,
                    "estimated_reward": p.estimated_reward,
                    "structural_score": p.structural_score
                }
                for p in top_paths
            ]
        }
        
        self.path_logs.append(log_entry)
        self.session_log.append(log_entry)
        
        self.logger.info(f"[MCTS] Generated {paths_generated} paths, selected top {len(top_paths)}")
        for p in top_paths:
            self.logger.info(f"  {p.path_id}: {' → '.join(p.operators)} (R={p.estimated_reward:.3f})")
    
    def log_operator_execution(
        self,
        path_id: str,
        step: int,
        operator_name: str,
        code: str,
        success: bool,
        error_message: str = "",
        state_before: Optional[Any] = None,
        state_after: Optional[Any] = None,
        execution_time: float = 0.0
    ):
        """Log operator execution"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "module": "SMG",
            "action": "execute_operator",
            "path_id": path_id,
            "step": step,
            "operator": operator_name,
            "code": code,
            "success": success,
            "error": error_message,
            "execution_time": execution_time,
            "state_before": state_before.to_dict() if state_before and hasattr(state_before, 'to_dict') else None,
            "state_after": state_after.to_dict() if state_after and hasattr(state_after, 'to_dict') else None
        }
        
        self.operator_logs.append(log_entry)
        self.session_log.append(log_entry)
        
        status = "✓" if success else "✗"
        self.logger.info(f"[SMG] {path_id} Step {step}: {operator_name} {status} ({execution_time:.2f}s)")
        if not success:
            self.logger.error(f"  Error: {error_message[:200]}")
    
    def log_reward_evaluation(
        self,
        path_id: str,
        step: int,
        operator_name: str,
        reward: Any
    ):
        """Log reward evaluation"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "module": "REWARD",
            "action": "evaluate",
            "path_id": path_id,
            "step": step,
            "operator": operator_name,
            "reward": reward.to_dict() if hasattr(reward, 'to_dict') else str(reward)
        }
        
        self.reward_logs.append(log_entry)
        self.session_log.append(log_entry)
        
        if hasattr(reward, 'to_dict'):
            r = reward.to_dict()
            self.logger.info(
                f"[REWARD] {path_id} Step {step}: Total={r.get('total_score', 0):.3f} "
                f"(exec={r.get('execution_success', 0):.1f}, "
                f"query={r.get('query_satisfaction', 0):.1f})"
            )
    
    def log_path_completion(
        self,
        path_id: str,
        cumulative_reward: float,
        execution_stopped: bool,
        stop_reason: str = ""
    ):
        """Log path completion"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "module": "SMG",
            "action": "path_complete",
            "path_id": path_id,
            "cumulative_reward": cumulative_reward,
            "execution_stopped": execution_stopped,
            "stop_reason": stop_reason
        }
        
        self.path_logs.append(log_entry)
        self.session_log.append(log_entry)
        
        self.logger.info(
            f"[SMG] {path_id} completed: reward={cumulative_reward:.3f}, "
            f"stopped={execution_stopped}"
        )
    
    def save_session_log(self):
        """Save all logs to files"""
        if not self.enable_file_logging:
            return
        
        # Save main session log
        session_file = self.log_dir / f"session_{self.session_id}.json"
        with open(session_file, 'w') as f:
            json.dump(self.session_log, f, indent=2, default=str)
        
        # Save operator logs
        operator_file = self.log_dir / f"operators_{self.session_id}.json"
        with open(operator_file, 'w') as f:
            json.dump(self.operator_logs, f, indent=2, default=str)
        
        # Save reward logs
        reward_file = self.log_dir / f"rewards_{self.session_id}.json"
        with open(reward_file, 'w') as f:
            json.dump(self.reward_logs, f, indent=2, default=str)
        
        # Save path logs
        path_file = self.log_dir / f"paths_{self.session_id}.json"
        with open(path_file, 'w') as f:
            json.dump(self.path_logs, f, indent=2, default=str)
        
        self.logger.info(f"Session logs saved to {self.log_dir}")
    
    def get_execution_summary(self) -> Dict[str, Any]:
        """Get summary of execution"""
        total_ops = len(self.operator_logs)
        successful_ops = sum(1 for log in self.operator_logs if log.get("success", False))
        
        total_reward = sum(
            log.get("reward", {}).get("total_score", 0)
            for log in self.reward_logs
        )
        
        return {
            "session_id": self.session_id,
            "total_operators": total_ops,
            "successful_operators": successful_ops,
            "failed_operators": total_ops - successful_ops,
            "success_rate": successful_ops / total_ops if total_ops > 0 else 0.0,
            "total_reward": total_reward,
            "average_reward": total_reward / total_ops if total_ops > 0 else 0.0,
            "paths_executed": len(self.path_logs),
            "log_files": [
                f"session_{self.session_id}.json",
                f"operators_{self.session_id}.json",
                f"rewards_{self.session_id}.json",
                f"paths_{self.session_id}.json"
            ]
        }
    
    def replay_path(self, path_id: str) -> List[Dict[str, Any]]:
        """
        Replay a specific path for debugging.
        Returns list of operations in order.
        """
        path_operations = [
            log for log in self.operator_logs
            if log.get("path_id") == path_id
        ]
        
        return sorted(path_operations, key=lambda x: x.get("step", 0))
    
    def print_summary(self):
        """Print execution summary to console"""
        summary = self.get_execution_summary()
        
        print("\n" + "="*70)
        print("DTR EXECUTION SUMMARY")
        print("="*70)
        print(f"Session ID: {summary['session_id']}")
        print(f"Total Operators: {summary['total_operators']}")
        print(f"  Successful: {summary['successful_operators']}")
        print(f"  Failed: {summary['failed_operators']}")
        print(f"  Success Rate: {summary['success_rate']*100:.1f}%")
        print(f"Total Reward: {summary['total_reward']:.3f}")
        print(f"Average Reward: {summary['average_reward']:.3f}")
        print(f"Paths Executed: {summary['paths_executed']}")
        print("="*70)


def create_dtr_logger(log_dir: str = "logs/dtr", enable_file_logging: bool = True) -> DTRLogger:
    """Factory function to create DTR logger"""
    return DTRLogger(log_dir, enable_file_logging)


if __name__ == "__main__":
    # Test logger
    logger = create_dtr_logger()
    
    # Simulate some logs
    from src.core.dtr_structures import Operator, OperatorType, TableState, RewardVector
    
    op1 = Operator("TEST_OP", OperatorType.DATA_UNDERSTANDING, "Test operator")
    logger.log_ado_extraction(
        "Test query",
        [op1],
        "Test response"
    )
    
    state = TableState(columns=["a", "b"], row_count=10, shape=(10, 2))
    logger.log_operator_execution(
        "PATH_A", 1, "TEST_OP",
        "df = df.head()", True, "",
        state, state, 0.5
    )
    
    reward = RewardVector(
        execution_success=1.0,
        query_satisfaction=0.8,
        code_reasonableness=0.9,
        efficiency=0.7,
        error_severity=0.0
    )
    reward.compute_total()
    
    logger.log_reward_evaluation("PATH_A", 1, "TEST_OP", reward)
    logger.log_path_completion("PATH_A", 0.85, False)
    
    logger.print_summary()
    logger.save_session_log()

