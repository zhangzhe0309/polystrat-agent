#!/usr/bin/env python3
"""
安全文件操作模块
- 原子写入（防止数据损坏）
- 正确的文件锁（对数据文件加锁）
- 事务性读取（读取时加锁，保证一致性）
"""
import json
import os
import fcntl
import tempfile
from pathlib import Path
from polystrat_logger import log, log_error

def atomic_write_json(file_path, data):
    """
    原子写入 JSON 文件
    
    正确做法：
    1. 对数据文件本身加锁（不是单独的锁文件）
    2. 使用临时文件+rename 原子操作
    3. 写入后 fsync 确保落盘
    
    Args:
        file_path: 文件路径
        data: 要写入的数据
    """
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 获取文件描述符并加锁
    fd = os.open(str(file_path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        # 获取排他锁
        fcntl.flock(fd, fcntl.LOCK_EX)
        
        # 写入临时文件
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(file_path.parent),
            prefix='.tmp_',
            suffix='.json'
        )
        try:
            # 写入临时文件
            content = json.dumps(data, indent=2, ensure_ascii=False).encode('utf-8')
            os.write(tmp_fd, content)
            os.fsync(tmp_fd)
            os.close(tmp_fd)
            
            # 原子重命名（在同一文件系统上是原子操作）
            os.rename(tmp_path, str(file_path))
            
        except Exception as e:
            print(f"⚠️ 原子写入失败: {e}")
            try:
                os.close(tmp_fd)
            except OSError:
                pass
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        
    finally:
        # 释放锁
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def atomic_read_json(file_path, default=None):
    """
    事务性读取 JSON 文件
    
    读取时加锁，保证读取到的是一致性数据
    
    Args:
        file_path: 文件路径
        default: 默认值（文件不存在时返回）
    
    Returns:
        读取的数据
    """
    if default is None:
        default = []
    
    file_path = Path(file_path)
    
    if not file_path.exists():
        return default
    
    # 获取文件描述符并加共享锁
    fd = os.open(str(file_path), os.O_RDONLY)
    try:
        # 获取共享锁（允许并发读，但阻塞写）
        fcntl.flock(fd, fcntl.LOCK_SH)
        
        # 读取文件内容
        content = os.read(fd, os.path.getsize(str(file_path)))
        
        if not content:
            return default
        
        return json.loads(content.decode('utf-8'))
        
    except json.JSONDecodeError as e:
        log_error("file_ops", e, f"JSON解析失败: {file_path}")
        return default
    except Exception as e:
        log_error("file_ops", e, f"读取失败: {file_path}")
        return default
    finally:
        # 释放锁
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def append_to_json_array(file_path, new_item):
    """
    原子追加到 JSON 数组
    
    整个操作在锁保护下完成，保证一致性
    
    Args:
        file_path: 文件路径
        new_item: 要追加的元素
    """
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 获取文件描述符并加锁
    fd = os.open(str(file_path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        # 获取排他锁
        fcntl.flock(fd, fcntl.LOCK_EX)
        
        # 读取现有数据
        try:
            content = os.read(fd, os.path.getsize(str(file_path)))
            data = json.loads(content.decode('utf-8')) if content else []
        except (json.JSONDecodeError, FileNotFoundError):
            data = []
        
        # 追加新数据
        data.append(new_item)
        
        # 写回文件
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        new_content = json.dumps(data, indent=2, ensure_ascii=False).encode('utf-8')
        os.write(fd, new_content)
        os.fsync(fd)
        
    finally:
        # 释放锁
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


# 便捷函数
def save_trades_safe(trades):
    """安全保存交易记录"""
    from config_center import TRADE_LOG
    atomic_write_json(TRADE_LOG, trades)

def load_trades_safe():
    """安全加载交易记录"""
    from config_center import TRADE_LOG
    return atomic_read_json(TRADE_LOG, default=[])

def append_trade_safe(trade_info):
    """安全追加交易记录"""
    from config_center import TRADE_LOG
    append_to_json_array(TRADE_LOG, trade_info)


if __name__ == "__main__":
    import time
    from concurrent.futures import ThreadPoolExecutor
    
    print("=" * 50)
    print("安全文件操作测试")
    print("=" * 50)
    
    test_file = Path("/tmp/test_atomic_write.json")
    
    # 清理
    if test_file.exists():
        test_file.unlink()
    
    # 测试1: 原子写入
    print("\n1. 原子写入测试:")
    test_data = [{"id": i, "data": f"item_{i}"} for i in range(100)]
    atomic_write_json(test_file, test_data)
    loaded = atomic_read_json(test_file)
    assert len(loaded) == 100, f"期望100条，实际{len(loaded)}条"
    print(f"   ✅ 写入100条，读取{len(loaded)}条")
    
    # 测试2: 并发安全
    print("\n2. 并发安全测试:")
    if test_file.exists():
        test_file.unlink()
    
    def writer(i):
        append_to_json_array(test_file, {"id": i, "thread": i})
        return i
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(writer, range(50)))
    
    loaded = atomic_read_json(test_file)
    assert len(loaded) == 50, f"期望50条，实际{len(loaded)}条"
    print(f"   ✅ 10线程并发写入50条，读取{len(loaded)}条")
    
    # 测试3: 便捷函数
    print("\n3. 便捷函数测试:")
    append_trade_safe({"test": True, "id": 999})
    trades = load_trades_safe()
    assert any(t.get("id") == 999 for t in trades)
    print(f"   ✅ append_trade_safe + load_trades_safe 正常")
    
    # 清理
    if test_file.exists():
        test_file.unlink()
    
    print("\n✅ 安全文件操作测试通过")
