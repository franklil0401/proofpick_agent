"""
DTR Framework - Configuration Management

Handles loading and managing configuration from files and environment.
"""

import os
import json
import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, field, asdict

from .logger import logger


@dataclass
class Config:
    """DTR Framework configuration"""
    
    # LLM settings
    llm_model: str = "gpt-3.5-turbo"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_provider: str = "openai"
    llm_temperature: float = 0.3
    llm_max_tokens: Optional[int] = None
    llm_max_retries: int = 5
    llm_retry_delay: float = 1.0
    
    # MCTS settings
    mcts_exploration_weight: float = 1.414
    mcts_max_iterations: int = 50
    mcts_max_path_length: int = 10
    mcts_top_k_paths: int = 2
    
    # SMG settings
    smg_max_execution_time: float = 60.0
    smg_enable_safety_checks: bool = True
    smg_save_memory: bool = True
    
    # Reward settings
    reward_weights: Dict[str, float] = field(default_factory=lambda: {
        "execution_success": 0.3,
        "query_satisfaction": 0.3,
        "code_reasonableness": 0.2,
        "efficiency": 0.1,
        "error_severity": 0.1
    })
    
    # Logging settings
    log_level: str = "INFO"
    log_dir: str = "logs"
    enable_file_logging: bool = True
    
    # Data settings
    data_sample_rows: int = 150
    data_dir: str = "data"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Config':
        """Create config from dictionary"""
        # Filter out unknown keys
        known_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_keys}
        return cls(**filtered)
    
    def save(self, filepath: str):
        """Save config to file (JSON or YAML)"""
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        data = self.to_dict()
        
        if path.suffix == '.json':
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
        elif path.suffix in ['.yaml', '.yml']:
            with open(path, 'w') as f:
                yaml.dump(data, f, default_flow_style=False)
        else:
            raise ValueError(f"Unsupported file format: {path.suffix}")
        
        logger.info(f"Config saved to {filepath}")
    
    @classmethod
    def load(cls, filepath: str) -> 'Config':
        """Load config from file"""
        path = Path(filepath)
        
        if not path.exists():
            logger.warning(f"Config file not found: {filepath}, using defaults")
            return cls()
        
        if path.suffix == '.json':
            with open(path, 'r') as f:
                data = json.load(f)
        elif path.suffix in ['.yaml', '.yml']:
            with open(path, 'r') as f:
                data = yaml.safe_load(f)
        else:
            raise ValueError(f"Unsupported file format: {path.suffix}")
        
        logger.info(f"Config loaded from {filepath}")
        return cls.from_dict(data)
    
    def update_from_env(self):
        """Update config from environment variables"""
        env_mapping = {
            'LLM_MODEL': 'llm_model',
            'LLM_BASE_URL': 'llm_base_url',
            'LLM_API_KEY': 'llm_api_key',
            'LLM_PROVIDER': 'llm_provider',
            'LLM_TEMPERATURE': ('llm_temperature', float),
            'LLM_MAX_TOKENS': ('llm_max_tokens', int),
            'LOG_LEVEL': 'log_level',
            'LOG_DIR': 'log_dir',
            'DATA_SAMPLE_ROWS': ('data_sample_rows', int),
        }
        
        for env_key, config_key in env_mapping.items():
            value = os.getenv(env_key)
            if value is not None:
                if isinstance(config_key, tuple):
                    attr_name, converter = config_key
                    try:
                        value = converter(value)
                    except ValueError:
                        logger.warning(f"Invalid value for {env_key}: {value}")
                        continue
                else:
                    attr_name = config_key
                
                setattr(self, attr_name, value)
                logger.debug(f"Updated {attr_name} from environment")


def load_config(config_file: Optional[str] = None) -> Config:
    """
    Load configuration from file and environment
    
    Priority:
    1. Environment variables (highest)
    2. Config file (if provided)
    3. Default values (lowest)
    
    Args:
        config_file: Path to config file (JSON or YAML)
    
    Returns:
        Config instance
    """
    # Start with defaults
    if config_file and Path(config_file).exists():
        config = Config.load(config_file)
    else:
        config = Config()
    
    # Override with environment variables
    config.update_from_env()
    
    return config


def create_default_config(filepath: str = "config/config.yaml"):
    """Create a default config file"""
    config = Config()
    config.save(filepath)
    logger.info(f"Default config created at {filepath}")


if __name__ == "__main__":
    # Test config
    config = Config()
    print("Default config:")
    print(json.dumps(config.to_dict(), indent=2))
    
    # Test save/load
    config.save("/tmp/test_config.yaml")
    loaded = Config.load("/tmp/test_config.yaml")
    print("\nLoaded config matches:", config.to_dict() == loaded.to_dict())

