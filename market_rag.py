#!/usr/bin/env python3
"""
轻量级市场 RAG 模块 — 借鉴 Polymarket 官方 chroma.py
- 语义搜索替代关键词匹配，提升市场筛选质量
- API-based Embeddings（零本地内存）
- 磁盘持久化向量索引
- 适配 961MB VPS

来源: https://github.com/Polymarket/agents 的 connectors/chroma.py
"""

import os
import json
import time
import hashlib
import requests
import numpy as np
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

# 缓存目录
from config_center import DATA_DIR

RAG_DATA_DIR = DATA_DIR / "market_rag"
RAG_DATA_DIR.mkdir(parents=True, exist_ok=True)

# Embedding 配置
EMBED_CACHE_DIR = RAG_DATA_DIR / "embeddings"
EMBED_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _get_embedding_api_config():
    """获取 embedding API 配置（优先 NVIDIA，降级 OpenAI）"""
    nvidia_key = os.environ.get("NVIDIA_API_KEY_2", os.environ.get("NVIDIA_API_KEY", ""))
    if nvidia_key:
        return {
            "url": "https://integrate.api.nvidia.com/v1/embeddings",
            "api_key": nvidia_key,
            "model": "nvidia/embed-qa-4",
        }
    
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if openai_key:
        return {
            "url": "https://api.openai.com/v1/embeddings",
            "api_key": openai_key,
            "model": "text-embedding-3-small",
        }
    
    return None


def embed_text(text: str) -> Optional[list[float]]:
    """
    调用 API 获取文本向量（带磁盘缓存）
    
    Args:
        text: 输入文本
    
    Returns:
        list[float] or None: 向量
    """
    # 缓存键
    cache_key = hashlib.md5(text[:500].encode()).hexdigest()
    cache_file = EMBED_CACHE_DIR / f"{cache_key}.json"
    
    # 检查缓存
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text())
            if cached.get("vector") and time.time() - cached.get("timestamp", 0) < 86400 * 7:
                return cached["vector"]
        except (json.JSONDecodeError, OSError) as e:
            print(f"⚠️ Embedding缓存读取失败: {e}")
    
    # API 调用
    config = _get_embedding_api_config()
    if not config:
        return _simple_tfidf_embed(text)
    
    try:
        resp = requests.post(
            config["url"],
            headers={
                "Authorization": f"Bearer {config['api_key']}",
                "Content-Type": "application/json",
            },
            json={
                "model": config["model"],
                "input": text[:500],
                "encoding_format": "float",
            },
            timeout=30,
        )
        
        if resp.status_code == 200:
            vector = resp.json()["data"][0]["embedding"]
            
            # 写入缓存
            try:
                cache_file.write_text(json.dumps({
                    "vector": vector,
                    "timestamp": time.time(),
                    "text_hash": cache_key,
                }))
            except (OSError, IOError) as e:
                print(f"⚠️ Embedding缓存写入失败: {e}")
            
            return vector
        else:
            # API 不可用，静默降级到 TF-IDF（只打印一次警告）
            if not hasattr(embed_text, '_warned'):
                print(f"⚠️ Embedding API 不可用 ({resp.status_code})，使用 TF-IDF 降级")
                embed_text._warned = True
            return _simple_tfidf_embed(text)
    
    except Exception as e:
        print(f"⚠️ Embedding 调用失败: {e}")
        return _simple_tfidf_embed(text)


def _simple_tfidf_embed(text: str, dim: int = 128) -> list[float]:
    """
    降级方案: 简单哈希向量化（无 API 调用时使用）
    精度较低但保证可用
    """
    words = text.lower().split()[:50]
    vector = [0.0] * dim
    for i, word in enumerate(words):
        h = int(hashlib.md5(word.encode()).hexdigest(), 16)
        idx = h % dim
        vector[idx] += 1.0
    
    # 归一化
    norm = sum(x * x for x in vector) ** 0.5
    if norm > 0:
        vector = [x / norm for x in vector]
    
    return vector


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算余弦相似度"""
    a_arr = np.array(a)
    b_arr = np.array(b)
    norm_a = np.linalg.norm(a_arr)
    norm_b = np.linalg.norm(b_arr)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a_arr, b_arr) / (norm_a * norm_b))


class MarketRAG:
    """
    轻量级市场向量搜索
    
    用法:
        rag = MarketRAG()
        rag.index_markets(markets_list)
        results = rag.search("politics election", top_k=5)
    """
    
    def __init__(self, db_path: str = None):
        self.db_path = Path(db_path) if db_path else RAG_DATA_DIR / "index"
        self.db_path.mkdir(parents=True, exist_ok=True)
        self.index: dict[str, dict] = {}
        self._load_index()
    
    def _load_index(self):
        """从磁盘加载索引"""
        index_file = self.db_path / "market_index.json"
        if index_file.exists():
            try:
                data = json.loads(index_file.read_text())
                # 不加载向量到内存，按需从缓存读取
                self.index = data.get("metadata", {})
            except (json.JSONDecodeError, OSError) as e:
                print(f"⚠️ RAG索引加载失败: {e}")
                self.index = {}
    
    def _save_index(self):
        """持久化索引元数据到磁盘"""
        index_file = self.db_path / "market_index.json"
        try:
            index_file.write_text(json.dumps({
                "metadata": self.index,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }, ensure_ascii=False))
        except Exception as e:
            print(f"⚠️ RAG 索引保存失败: {e}")
    
    def index_markets(self, markets: list[dict], force: bool = False):
        """
        将市场数据索引入向量库
        
        Args:
            markets: 市场列表 (来自 Gamma API)
            force: 是否强制重新索引
        """
        for market in markets:
            market_id = str(market.get("id", market.get("conditionId", "")))
            if not market_id:
                continue
            
            # 跳过已索引的（除非强制）
            if not force and market_id in self.index:
                continue
            
            # 构造搜索文本（参考官方 chroma.py 的做法：content_key="description"）
            # 同时加入 question 和其他关键信息，增强语义匹配
            from superforecaster import preprocess_market_description
            description = preprocess_market_description(market)
            question = market.get("question", "")
            search_text = f"{question} {description}"
            
            # 获取向量
            vector = embed_text(search_text)
            if not vector:
                continue
            
            # 存储元数据（不存向量到 index，向量在 embed_cache 中）
            self.index[market_id] = {
                "id": market_id,
                "question": question,
                "description": description[:200],
                "outcomes": market.get("outcomes"),
                "outcomePrices": market.get("outcomePrices"),
                "clobTokenIds": market.get("clobTokenIds"),
                "volume": market.get("volume", market.get("volumeNum", 0)),
                "liquidity": market.get("liquidity", market.get("liquidityNum", 0)),
                "active": market.get("active", True),
                "embed_cache_key": hashlib.md5(search_text[:500].encode()).hexdigest(),
                "indexed_at": time.time(),
            }
        
        self._save_index()
        print(f"✅ 索引完成: {len(self.index)} 个市场")
    
    def search(self, query: str, top_k: int = 5, active_only: bool = True) -> list[dict]:
        """
        语义搜索最相关的市场
        
        Args:
            query: 搜索查询 (e.g., "politics election 2026")
            top_k: 返回前 K 个结果
            active_only: 仅返回活跃市场
        
        Returns:
            list[dict]: 匹配的市场列表，按相关度排序
        """
        query_vector = embed_text(query)
        if not query_vector:
            return []
        
        results = []
        for market_id, meta in self.index.items():
            # 过滤非活跃市场
            if active_only and not meta.get("active", True):
                continue
            
            # 从缓存读取向量
            cache_key = meta.get("embed_cache_key", "")
            cache_file = EMBED_CACHE_DIR / f"{cache_key}.json"
            if not cache_file.exists():
                continue
            
            try:
                cached = json.loads(cache_file.read_text())
                market_vector = cached.get("vector")
                if not market_vector:
                    continue
            except (json.JSONDecodeError, KeyError) as e:
                print(f"⚠️ 缓存向量读取失败: {e}")
                continue
            
            # 计算相似度
            score = cosine_similarity(query_vector, market_vector)
            results.append((score, meta))
        
        # 排序
        results.sort(key=lambda x: x[0], reverse=True)
        
        return [
            {
                "score": round(score, 4),
                "market": meta,
            }
            for score, meta in results[:top_k]
        ]
    
    def search_for_news_context(self, news_text: str, top_k: int = 3) -> list[dict]:
        """
        用新闻文本作为查询，找到最相关的市场
        这是官方 chroma.py 的核心用法：用 RAG 找到与查询相关的市场
        
        Args:
            news_text: 新闻文本
            top_k: 返回数量
        
        Returns:
            list[dict]: 与新闻最相关的市场
        """
        return self.search(query=news_text[:300], top_k=top_k)
    
    def get_stats(self) -> dict:
        """获取索引统计"""
        active = sum(1 for m in self.index.values() if m.get("active", True))
        index_file = self.db_path / "market_index.json"
        size_mb = index_file.stat().st_size / 1024 / 1024 if index_file.exists() else 0
        return {
            "total_markets": len(self.index),
            "active_markets": active,
            "index_size_mb": round(size_mb, 2),
        }


def build_rag_from_gamma_api(limit: int = 200) -> MarketRAG:
    """
    从 Gamma API 全量拉取市场并构建 RAG 索引
    
    Args:
        limit: 每页数量
    
    Returns:
        MarketRAG: 构建好的 RAG 实例
    """
    gamma_url = "https://gamma-api.polymarket.com/markets"
    all_markets = []
    offset = 0
    
    while True:
        params = {
            "active": True,
            "closed": False,
            "archived": False,
            "limit": limit,
            "offset": offset,
        }
        
        try:
            resp = requests.get(gamma_url, params=params, timeout=15)
            if resp.status_code != 200:
                print(f"⚠️ Gamma API 错误: {resp.status_code}")
                break
            
            batch = resp.json()
            all_markets.extend(batch)
            print(f"  已获取 {len(all_markets)} 个市场...")
            
            if len(batch) < limit:
                break
            offset += limit
            
            # 限制总量（VPS 内存考虑）
            if len(all_markets) >= 1000:
                break
        
        except Exception as e:
            print(f"⚠️ 获取市场失败: {e}")
            break
    
    print(f"📊 共获取 {len(all_markets)} 个市场")
    
    rag = MarketRAG()
    rag.index_markets(all_markets)
    return rag


if __name__ == "__main__":
    print("=== MarketRAG 测试 ===\n")
    
    # 测试1: Embedding
    print("1. 测试 Embedding API:")
    vec = embed_text("Will Bitcoin reach $100k?")
    if vec:
        print(f"   ✅ 向量维度: {len(vec)}")
        print(f"   前5维: {vec[:5]}")
    else:
        print("   ❌ Embedding 不可用")
    
    # 测试2: 相似度
    print("\n2. 测试余弦相似度:")
    v1 = embed_text("Bitcoin price prediction")
    v2 = embed_text("Cryptocurrency market forecast")
    v3 = embed_text("Weather forecast for tomorrow")
    if v1 and v2 and v3:
        print(f"   相关文本相似度: {cosine_similarity(v1, v2):.4f}")
        print(f"   无关文本相似度: {cosine_similarity(v1, v3):.4f}")
    
    # 测试3: RAG 索引
    print("\n3. 测试 MarketRAG:")
    rag = MarketRAG()
    stats = rag.get_stats()
    print(f"   索引统计: {stats}")
    
    if stats["total_markets"] == 0:
        print("   索引为空，尝试从 Gamma API 构建...")
        print("   (运行 build_rag_from_gamma_api() 来构建索引)")
    
    print("\n✅ MarketRAG 模块加载成功")
