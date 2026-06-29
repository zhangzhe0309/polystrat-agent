#!/usr/bin/env python3
"""
密钥管理模块
- 安全加载密钥
- 使用审计日志
- 避免全局变量暴露
"""
import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from polystrat_logger import log

# 审计日志
from config_center import KEY_AUDIT_LOG as AUDIT_LOG
AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)

# 审计日志记录器
audit_logger = logging.getLogger("key_audit")
audit_logger.setLevel(logging.INFO)

# 添加文件处理器
if not audit_logger.handlers:
    handler = logging.FileHandler(AUDIT_LOG)
    handler.setFormatter(logging.Formatter('%(asctime)s | %(message)s'))
    audit_logger.addHandler(handler)

class KeyManager:
    """
    密钥管理器
    - 安全加载密钥
    - 记录使用日志
    - 避免密钥泄露
    """
    
    def __init__(self):
        self._keys = {}
        self._loaded = False
    
    def _load_keys(self):
        """加载密钥（只加载一次）"""
        if self._loaded:
            return
        
        env_file = os.path.expanduser('~/.hermes/profiles/life/.env')
        
        try:
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if '=' in line and not line.startswith('#'):
                        key, value = line.split('=', 1)
                        # 只加载需要的密钥
                        if any(keyword in key for keyword in ['API_KEY', 'PRIVATE_KEY', 'TOKEN']):
                            self._keys[key] = value
            
            self._loaded = True
            audit_logger.info("密钥加载成功")
            
        except Exception as e:
            audit_logger.error(f"密钥加载失败: {e}")
            log.error(f"密钥加载失败: {e}")
    
    def get_key(self, key_name, default=""):
        """
        获取密钥
        
        Args:
            key_name: 密钥名称
            default: 默认值
        
        Returns:
            str: 密钥值
        """
        if not self._loaded:
            self._load_keys()
        
        value = self._keys.get(key_name, default)
        
        # 记录访问日志（不记录密钥值）
        audit_logger.info(f"访问密钥: {key_name}")
        
        return value
    
    def get_masked_key(self, key_name, show_chars=4):
        """
        获取脱敏密钥（用于日志显示）
        
        Args:
            key_name: 密钥名称
            show_chars: 显示前几位
        
        Returns:
            str: 脱敏后的密钥
        """
        value = self.get_key(key_name)
        if not value:
            return "***未设置***"
        
        if len(value) <= show_chars:
            return "***"
        
        return value[:show_chars] + "***"
    
    def validate_keys(self, required_keys):
        """
        验证必需的密钥是否存在
        
        Args:
            required_keys: 必需的密钥列表
        
        Returns:
            tuple: (是否全部存在, 缺失的密钥列表)
        """
        if not self._loaded:
            self._load_keys()
        
        missing = []
        for key in required_keys:
            if not self._keys.get(key):
                missing.append(key)
        
        return len(missing) == 0, missing

# 全局密钥管理器实例
_key_manager = KeyManager()

def get_api_key(key_name):
    """获取 API 密钥"""
    return _key_manager.get_key(key_name)

def get_masked_api_key(key_name):
    """获取脱敏 API 密钥"""
    return _key_manager.get_masked_key(key_name)

def validate_required_keys(required_keys):
    """验证必需的密钥"""
    return _key_manager.validate_keys(required_keys)

if __name__ == "__main__":
    print("=" * 50)
    print("密钥管理模块测试")
    print("=" * 50)
    
    # 测试获取密钥
    print("\n1. 获取密钥:")
    nvidia_key = get_api_key("NVIDIA_API_KEY_2")
    print(f"   NVIDIA Key: {get_masked_api_key('NVIDIA_API_KEY_2')}")
    
    glm_key = get_api_key("GLM_API_KEY")
    print(f"   GLM Key: {get_masked_api_key('GLM_API_KEY')}")
    
    # 测试验证密钥
    print("\n2. 验证密钥:")
    required = ["NVIDIA_API_KEY_2", "GLM_API_KEY", "MISSING_KEY"]
    all_valid, missing = validate_required_keys(required)
    print(f"   全部存在: {all_valid}")
    if missing:
        print(f"   缺失: {missing}")
    
    # 检查审计日志
    print(f"\n3. 审计日志: {AUDIT_LOG}")
    if AUDIT_LOG.exists():
        with open(AUDIT_LOG) as f:
            lines = f.readlines()
            print(f"   日志条数: {len(lines)}")
            for line in lines[-3:]:
                print(f"   {line.strip()}")
    
    print("\n✅ 密钥管理模块测试完成")
