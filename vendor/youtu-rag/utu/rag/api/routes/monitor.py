"""Storage monitoring routes"""
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from smartbuy.observability import agent_monitor

from ..services.monitor_service import MonitorService

logger = logging.getLogger(__name__)
router = APIRouter()

# Global singleton
monitor_service = MonitorService()


@router.get("/health/storage")
async def get_storage_health():
    """
    Get storage backend health status (JSON format)

    Returns:
        Health status of all storage backends (Vector Store, Database, Object Storage).
    """
    try:
        return monitor_service.get_storage_health()
    except Exception as exc:
        logger.error("Get storage health error type=%s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Storage health unavailable") from None


@router.get("/health/storage/metrics")
async def get_storage_metrics():
    """
    Get detailed storage backend metrics (JSON format)

    Returns:
        Detailed metrics including capacity, usage rate, etc.
    """
    try:
        return monitor_service.get_storage_metrics()
    except Exception as exc:
        logger.error("Get storage metrics error type=%s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Storage metrics unavailable") from None


@router.get("/monitor", response_class=HTMLResponse)
async def get_storage_monitor_dashboard():
    """
    Get storage monitoring dashboard (HTML format)

    Returns:
        A complete HTML page displaying storage health status
    """
    try:
        storage_html = monitor_service.get_storage_dashboard_html()
        snapshot = agent_monitor.snapshot()
        panel = f"""
        <section style="margin:24px;padding:20px;border:1px solid #dbeafe;border-radius:12px;background:#eff6ff">
          <h2>SmartBuy Agent（脱敏摘要）</h2>
          <p>运行数：{snapshot['run_count']} ｜ 降级运行：{snapshot['degraded_run_count']} ｜
             拒答数：{snapshot['abstain_count']} ｜ 平均延迟：{snapshot['average_latency_ms']} ms ｜
             P95：{snapshot['p95_latency_ms']} ms ｜ 估算成本：¥{snapshot['estimated_cost_cny']}</p>
          <p>详细的可审计步骤请查看 WebUI 工具卡片或 <code>/api/smartbuy/monitor</code>；
             这里不显示 Prompt、密钥或隐藏思维链。</p>
        </section>
        """
        return storage_html.replace("</body>", panel + "</body>")
    except Exception as exc:
        logger.error("Get storage dashboard error type=%s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Storage dashboard unavailable") from None
