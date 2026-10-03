"""测试估值 API 端点的脚本。"""

import requests
from datetime import date

BASE_URL = "http://localhost:5000"


def test_api():
    """测试估值 API。"""
    print("=" * 60)
    print("测试估值 API 端点")
    print("=" * 60)

    # 1. 测试创建估值运行
    print("\n1. 创建估值运行 (POST /api/valuation/runs)")
    print("-" * 60)

    # 注意：这个请求会返回 401，因为需要认证
    response = requests.post(
        f"{BASE_URL}/api/valuation/runs",
        json={
            "valuation_date": str(date.today()),
            "run_type": "scheduled",
        },
    )
    print(f"状态码: {response.status_code}")
    print(f"响应: {response.json()}")

    if response.status_code == 401:
        print("\n✓ 正确返回 401 - 需要用户认证")

    # 2. 测试获取估值运行列表
    print("\n2. 获取估值运行列表 (GET /api/valuation/runs)")
    print("-" * 60)

    response = requests.get(f"{BASE_URL}/api/valuation/runs")
    print(f"状态码: {response.status_code}")
    print(f"响应: {response.json()}")

    # 3. 测试获取当前运行
    print("\n3. 获取当前运行 (GET /api/valuation/runs/current)")
    print("-" * 60)

    response = requests.get(f"{BASE_URL}/api/valuation/runs/current")
    print(f"状态码: {response.status_code}")
    print(f"响应: {response.json()}")

    # 4. 测试查询组合估值快照
    print("\n4. 查询组合估值快照 (GET /api/valuation/snapshots/portfolio)")
    print("-" * 60)

    response = requests.get(
        f"{BASE_URL}/api/valuation/snapshots/portfolio",
        params={
            "from_date": "2024-01-01",
            "to_date": str(date.today()),
        },
    )
    print(f"状态码: {response.status_code}")
    print(f"响应: {response.json()}")

    # 5. 测试查询持仓估值快照
    print("\n5. 查询持仓估值快照 (GET /api/valuation/snapshots/positions)")
    print("-" * 60)

    response = requests.get(
        f"{BASE_URL}/api/valuation/snapshots/positions",
        params={
            "snapshot_date": str(date.today()),
        },
    )
    print(f"状态码: {response.status_code}")
    print(f"响应: {response.json()}")

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
    print("\n说明:")
    print("- 所有端点都需要用户认证 (@login_required)")
    print("- 未认证请求会返回 401 状态码")
    print("- 需要先实现用户登录功能才能完整测试")


if __name__ == "__main__":
    test_api()
