"""
MODULE 2 - MCTS Path Planner

PURPOSE:
- Generate multiple candidate execution paths from operators
- Select TOP 2 paths by cumulative reward estimate

CRITICAL CONSTRAINTS:
- NO code generation
- NO dataframe execution
- NO LLM calls
- NO simulation via pandas or SQL

Planning Logic:
- Treat each path as a sequence of operators
- Use Q-UCB / P-UCB variant for path selection
- Rapidly iterate to generate ~20 candidate paths
- Rewards are heuristic and structural only
"""

import math
import random
from typing import List, Dict, Any, Set, Tuple, Optional
from collections import defaultdict
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
from src.core.dtr_structures import Operator, ExecutionPath, MCTSNode


class MCTSPlanner:
    """
    MCTS-based path planner.
    Generates execution paths WITHOUT code generation or LLM.
    """
    
    def __init__(
        self,
        exploration_weight: float = 1.414,
        max_iterations: int = 100,
        max_path_length: int = 10
    ):
        """
        Args:
            exploration_weight: UCB exploration parameter (sqrt(2) by default)
            max_iterations: Number of MCTS iterations
            max_path_length: Maximum operators in a path
        """
        self.exploration_weight = exploration_weight
        self.max_iterations = max_iterations
        self.max_path_length = max_path_length
        
        # Root node
        self.root = None
        
        # Track generated paths
        self.generated_paths: List[ExecutionPath] = []
    
    def plan(
        self,
        operators: List[Operator],
        initial_state: Set[str],
        num_paths: int = 2
    ) -> List[ExecutionPath]:
        """
        Generate candidate execution paths.
        
        Args:
            operators: List of operators from ADO
            initial_state: Initial available state (e.g., {"file_loaded", "schema"})
            num_paths: Number of top paths to return (default: 2)
        
        Returns:
            List of ExecutionPath objects (top num_paths paths)
        """
        if not operators:
            return []
        
        # Initialize root
        self.root = MCTSNode(
            operator_name="ROOT",
            available_state=initial_state.copy(),
            completed_ops=set()
        )
        
        self.generated_paths = []
        
        # Run MCTS iterations
        for iteration in range(self.max_iterations):
            # Select path via tree traversal
            path, leaf_node = self._select_path(self.root, operators)
            
            if not path:
                continue
            
            # Evaluate path (heuristic only, no execution)
            reward = self._evaluate_path_heuristic(path, operators)
            
            # Backpropagate reward
            self._backpropagate(leaf_node, reward)
            
            # Store path
            path_obj = ExecutionPath(
                operators=[op.name for op in path],
                estimated_reward=reward,
                structural_score=self._compute_structural_score(path, operators),
                path_id=f"path_{iteration}",
                reasoning=f"MCTS iteration {iteration}"
            )
            self.generated_paths.append(path_obj)
        
        # Select top paths
        top_paths = self._select_top_paths(k=num_paths)
        
        return top_paths
    
    def _select_path(
        self,
        root: MCTSNode,
        operators: List[Operator]
    ) -> Tuple[List[Operator], MCTSNode]:
        """
        Select a path through the tree using UCB.
        Returns (operator_sequence, leaf_node)
        """
        path = []
        current = root
        available_ops = set(op.name for op in operators)
        
        # Traverse tree
        for depth in range(self.max_path_length):
            # Check if all operators used or no valid children
            if not available_ops or len(current.completed_ops) >= len(operators):
                break
            
            # Get feasible operators
            feasible = self._get_feasible_operators(
                operators,
                current.available_state,
                current.completed_ops
            )
            
            if not feasible:
                break
            
            # Select next operator using UCB
            selected_op = self._select_operator_ucb(
                current,
                feasible,
                operators
            )
            
            if selected_op is None:
                break
            
            path.append(selected_op)
            
            # Find or create child node
            child = self._get_or_create_child(current, selected_op)
            current = child
            
            # Update state
            current.completed_ops = current.parent.completed_ops | {selected_op.name}
            current.available_state = current.parent.available_state.copy()
            
            # Add produced columns/state to available
            for col in selected_op.produced_columns:
                current.available_state.add(col)
            
            # Simple postcondition simulation (add operator name as available state)
            current.available_state.add(selected_op.name.lower())
        
        return path, current
    
    def _get_feasible_operators(
        self,
        operators: List[Operator],
        available_state: Set[str],
        completed_ops: Set[str]
    ) -> List[Operator]:
        """
        Get operators that can be executed given current state.
        Check dependency satisfaction heuristically.
        """
        feasible = []
        
        for op in operators:
            # Skip if already used
            if op.name in completed_ops:
                continue
            
            # Check if required columns are available (simplified check)
            can_execute = True
            for req_col in op.required_columns:
                if req_col and req_col not in available_state:
                    can_execute = False
                    break
            
            if can_execute:
                feasible.append(op)
        
        return feasible
    
    def _select_operator_ucb(
        self,
        parent: MCTSNode,
        feasible_ops: List[Operator],
        all_operators: List[Operator]
    ) -> Optional[Operator]:
        """Select operator using UCB formula"""
        
        if not feasible_ops:
            return None
        
        # If there are unvisited operators, pick one randomly
        unvisited = []
        for op in feasible_ops:
            # Check if this operator has been explored from this node
            child_exists = any(c.operator_name == op.name for c in parent.children)
            if not child_exists:
                unvisited.append(op)
        
        if unvisited:
            return random.choice(unvisited)
        
        # Otherwise, use UCB
        best_op = None
        best_score = -float('inf')
        
        parent_visits = parent.visit_count
        
        for op in feasible_ops:
            # Find corresponding child node
            child = next((c for c in parent.children if c.operator_name == op.name), None)
            
            if child is None:
                # Shouldn't happen, but handle gracefully
                score = float('inf')
            else:
                score = child.ucb_score(parent_visits, self.exploration_weight)
            
            if score > best_score:
                best_score = score
                best_op = op
        
        return best_op
    
    def _get_or_create_child(
        self,
        parent: MCTSNode,
        operator: Operator
    ) -> MCTSNode:
        """Get existing child node or create new one"""
        
        # Check if child exists
        for child in parent.children:
            if child.operator_name == operator.name:
                return child
        
        # Create new child
        child = MCTSNode(
            operator_name=operator.name,
            parent=parent,
            prior_prob=0.1,  # Uniform prior
            available_state=parent.available_state.copy(),
            completed_ops=parent.completed_ops.copy()
        )
        
        parent.children.append(child)
        
        return child
    
    def _evaluate_path_heuristic(
        self,
        path: List[Operator],
        all_operators: List[Operator]
    ) -> float:
        """
        Evaluate path using HEURISTICS ONLY.
        No code execution, no LLM, no simulation.
        
        Returns reward score (0-1 range preferred)
        """
        if not path:
            return 0.0
        
        reward = 0.5  # Base reward
        
        # Reward 1: Path completeness
        # Prefer paths that use more necessary operators
        completeness = len(path) / min(len(all_operators), self.max_path_length)
        reward += 0.2 * completeness
        
        # Reward 2: Operator diversity
        categories = set(op.category for op in path)
        diversity = len(categories) / 5.0  # Normalize by ~5 categories
        reward += 0.1 * diversity
        
        # Reward 3: Logical ordering (heuristic)
        order_score = self._check_logical_order(path)
        reward += 0.2 * order_score
        
        # Penalty: Excessive length
        if len(path) > self.max_path_length * 0.8:
            reward -= 0.1
        
        # Normalize to 0-1
        reward = max(0.0, min(1.0, reward))
        
        return reward
    
    def _check_logical_order(self, path: List[Operator]) -> float:
        """
        Check if operators are in logical order (heuristic).
        Returns score 0-1.
        """
        score = 1.0
        
        # Heuristic rules:
        # 1. Data understanding should come before transformation
        # 2. Filtering before aggregation
        # 3. Cleaning before analysis
        
        understanding_ops = {"DETECT_SCHEMA", "INSPECT_COLUMN"}
        transformation_ops = {"DERIVE_COLUMN", "FILTER_ROWS", "SELECT_COLUMNS"}
        aggregation_ops = {"GROUP_BY", "AGGREGATE"}
        
        last_understanding_idx = -1
        first_aggregation_idx = len(path)
        
        for i, op in enumerate(path):
            if op.name in understanding_ops:
                last_understanding_idx = i
            if op.name in aggregation_ops and first_aggregation_idx == len(path):
                first_aggregation_idx = i
        
        # Penalize if understanding comes after aggregation
        if last_understanding_idx > first_aggregation_idx:
            score -= 0.3
        
        # Reward if GROUP_BY comes before AGGREGATE
        groupby_idx = next((i for i, op in enumerate(path) if op.name == "GROUP_BY"), -1)
        agg_idx = next((i for i, op in enumerate(path) if op.name == "AGGREGATE"), -1)
        
        if groupby_idx >= 0 and agg_idx >= 0:
            if groupby_idx < agg_idx:
                score += 0.2
            else:
                score -= 0.2
        
        return max(0.0, min(1.0, score))
    
    def _compute_structural_score(
        self,
        path: List[Operator],
        all_operators: List[Operator]
    ) -> float:
        """
        Compute structural validity score.
        Check dependency satisfaction.
        """
        score = 1.0
        available = set()
        
        for op in path:
            # Check if required columns are available
            for req_col in op.required_columns:
                if req_col and req_col not in available:
                    score -= 0.1  # Penalty for missing dependency
            
            # Add produced columns
            for prod_col in op.produced_columns:
                available.add(prod_col)
            
            # Add operator name to available state
            available.add(op.name.lower())
        
        return max(0.0, score)
    
    def _backpropagate(self, node: MCTSNode, reward: float):
        """
        Backpropagate reward up the tree.
        
        Updates N (visit count) and Q (cumulative reward) for each node.
        
        Formula:
            node.N += 1
            node.Q += reward
        
        Then selection uses PUCB:
            PUCB(s,a) = Q(s,a)/N(s,a) + c * P(a|s) * sqrt(N(s)) / (1 + N(s,a))
        """
        current = node
        
        while current is not None:
            # Update visit count and cumulative reward
            current.visit_count += 1  # N += 1
            current.total_reward += reward  # Q += reward
            
            # Update Q-value (average reward)
            current.q_value = current.total_reward / current.visit_count if current.visit_count > 0 else 0.0
            
            current = current.parent
    
    def update_from_real_execution(
        self,
        path_operators: List[str],
        aggregated_reward: float
    ):
        """
        Update MCTS tree with real execution feedback from SMG.
        
        This allows MCTS to learn from actual executions, not just heuristics.
        Call this after SMG executes a path and generates real rewards.
        
        Args:
            path_operators: List of operator names that were executed
            aggregated_reward: Aggregated reward from real execution
        """
        if not self.root:
            return
        
        # Find the path in the tree
        current = self.root
        for op_name in path_operators:
            # Find child with this operator
            child = next((c for c in current.children if c.operator_name == op_name), None)
            if child is None:
                # Path not in tree, can't update
                return
            current = child
        
        # Backpropagate real reward
        self._backpropagate(current, aggregated_reward)
        
        print(f"  [MCTS] Updated tree with real reward {aggregated_reward:.3f} for path: {' → '.join(path_operators)}")
    
    def _select_top_paths(self, k: int = 2) -> List[ExecutionPath]:
        """Select top k paths by estimated reward"""
        
        if not self.generated_paths:
            return []
        
        # Remove duplicate paths
        unique_paths = {}
        for path in self.generated_paths:
            key = tuple(path.operators)
            if key not in unique_paths or path.estimated_reward > unique_paths[key].estimated_reward:
                unique_paths[key] = path
        
        # Sort by estimated reward
        sorted_paths = sorted(
            unique_paths.values(),
            key=lambda p: p.estimated_reward,
            reverse=True
        )
        
        # Take top k
        top_k = sorted_paths[:k]
        
        # Assign path IDs
        for i, path in enumerate(top_k):
            path.path_id = f"PATH_{chr(65 + i)}"  # PATH_A, PATH_B, ...
            path.reasoning = f"Top {i+1} path (reward={path.estimated_reward:.3f}, structural={path.structural_score:.3f})"
        
        return top_k


def test_mcts_planner():
    """Test MCTS planner"""
    from src.modules.ado_module import OPERATOR_BY_NAME
    
    # Create test operators
    operators = [
        OPERATOR_BY_NAME["DETECT_SCHEMA"],
        OPERATOR_BY_NAME["GROUP_BY"],
        OPERATOR_BY_NAME["AGGREGATE"],
        OPERATOR_BY_NAME["SORT_VALUES"],
    ]
    
    planner = MCTSPlanner(
        exploration_weight=1.4,
        max_iterations=50,
        max_path_length=6
    )
    
    initial_state = {"file_loaded", "schema"}
    
    print("Running MCTS planner...")
    paths = planner.plan(operators, initial_state)
    
    print(f"\nGenerated {len(paths)} top paths:")
    for path in paths:
        print(f"\n{path}")
        print(f"  Operators: {' → '.join(path.operators)}")
        print(f"  Reward: {path.estimated_reward:.3f}")
        print(f"  Structural Score: {path.structural_score:.3f}")
        print(f"  Reasoning: {path.reasoning}")
    
    return paths


if __name__ == "__main__":
    test_mcts_planner()

