"""
选股 Agent 主入口
支持命令行传入股票代码列表，输出7维度完整分析报告

使用示例：
    python main.py 000001
    python main.py 000001 600519 300750
    python main.py --output report.json 000001 600519
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from typing import Optional

from config.settings import settings
from graph.workflow import run_batch_analysis, run_stock_analysis


def format_score_bar(score: float, width: int = 20) -> str:
    """将分数转为可视化进度条"""
    filled = int(score / 100 * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {score:.1f}/100"


def get_rating_label(score: float) -> str:
    """根据分数返回评级描述"""
    if score >= 85:
        return "★★★★★ 强烈推荐"
    elif score >= 70:
        return "★★★★  推荐关注"
    elif score >= 55:
        return "★★★   观望"
    elif score >= 40:
        return "★★    谨慎"
    else:
        return "★     回避"


def print_analysis_report(state: dict) -> None:
    """
    格式化打印7维度分析报告到控制台

    Args:
        state: 工作流最终状态
    """
    stock_code = state.get("stock_code", "未知")
    supervisor_result = state.get("supervisor_result", {})
    final_report = supervisor_result.get("final_report", {})
    sub_scores = supervisor_result.get("sub_scores", {})
    errors = state.get("errors", [])

    print("\n" + "=" * 70)
    print(f"  股票分析报告 - {stock_code}  （7维度选股系统）")
    print(f"  生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # 综合评分
    total_score = float(final_report.get("综合得分", supervisor_result.get("score", 0)))
    print(f"\n【综合评分】{format_score_bar(total_score)}")
    print(f"【投资评级】{get_rating_label(total_score)}")

    # 7维度评分（带权重）
    if sub_scores:
        print("\n【7维度评分】")
        dims = [
            ("policy",       "条件一：政策支持   ", "20%"),
            ("industry",     "条件二：行业龙头   ", "15%"),
            ("shareholder",  "条件三：股东结构   ", "15%"),
            ("supply_demand","条件四：供需涨价   ", "20%"),
            ("trend",        "条件五：中长期趋势 ", "10%"),
            ("catalyst",     "条件六：转折催化剂 ", "10%"),
            ("technical",    "条件七：技术量能   ", "10%"),
        ]
        for key, label, weight in dims:
            score = sub_scores.get(key, 0)
            bar = format_score_bar(float(score))
            print(f"  {label}（{weight}）：{bar}")
        print(f"  {'─'*50}")
        weighted = sub_scores.get("weighted_total", total_score)
        print(f"  加权综合分：{weighted:.1f}/100")

    # 7条件达标情况
    conditions = final_report.get("7条件达标情况", {})
    if conditions:
        print("\n【7条件达标情况】")
        for cond_name, cond_data in conditions.items():
            if isinstance(cond_data, dict):
                is_ok = "✓" if cond_data.get("是否达标") else "✗"
                score = cond_data.get("得分", "N/A")
                brief = cond_data.get("简评", "")
                print(f"  {is_ok} {cond_name}：{score}分  {brief}")

    # 核心投资逻辑
    best_logic = final_report.get("最强逻辑", "")
    if best_logic:
        print(f"\n【最强投资逻辑】\n  {best_logic}")

    core_logic = final_report.get("核心投资逻辑", "")
    if core_logic:
        print(f"\n【核心投资逻辑】\n  {core_logic}")

    # 操作建议
    operation = final_report.get("操作建议", {})
    if operation:
        print("\n【操作建议】")
        print(f"  建议操作：{operation.get('建议', 'N/A')}")
        print(f"  参考买入区间：{operation.get('参考买入区间', 'N/A')}")
        print(f"  参考止损位：{operation.get('参考止损位', 'N/A')}")
        print(f"  参考目标价：{operation.get('参考目标价', 'N/A')}")
        print(f"  持仓周期：{operation.get('持仓周期', 'N/A')}")
        print(f"  仓位建议：{operation.get('仓位建议', 'N/A')}")

    # 主要优势
    advantages = final_report.get("主要优势", [])
    if advantages:
        print("\n【主要优势】")
        for adv in advantages:
            print(f"  ✓ {adv}")

    # 主要风险
    risks = final_report.get("主要风险", [])
    if risks:
        print("\n【主要风险】")
        for risk in risks:
            print(f"  ✗ {risk}")

    # 分析摘要
    summary = final_report.get("分析摘要", "")
    if summary:
        print(f"\n【分析摘要】\n  {summary}")

    # 错误警告
    if errors:
        print(f"\n【分析警告】（{len(errors)}个）")
        for i, err in enumerate(errors[:3], 1):
            print(f"  警告{i}：{str(err)[:100]}...")

    print("\n" + "-" * 70)
    print("  免责声明：以上分析仅供参考，不构成投资建议，投资有风险，入市需谨慎")
    print("=" * 70 + "\n")


def print_batch_summary(results: list[dict]) -> None:
    """
    打印批量分析的汇总排名

    Args:
        results: 多只股票的分析结果列表
    """
    print("\n" + "=" * 70)
    print("  批量分析汇总排名")
    print("=" * 70)

    scored_stocks = []
    for state in results:
        stock_code = state.get("stock_code", "未知")
        supervisor_result = state.get("supervisor_result", {})
        final_report = supervisor_result.get("final_report", {})
        score = float(final_report.get("综合得分", supervisor_result.get("score", 0)))
        rating = get_rating_label(score)
        operation = final_report.get("操作建议", {}).get("建议", "N/A")
        scored_stocks.append((stock_code, score, rating, operation))

    scored_stocks.sort(key=lambda x: x[1], reverse=True)

    print(f"\n{'排名':<6}{'股票代码':<12}{'综合评分':<10}{'评级':<20}{'建议操作'}")
    print("-" * 70)
    for rank, (code, score, rating, operation) in enumerate(scored_stocks, 1):
        print(f"{rank:<6}{code:<12}{score:<10.1f}{rating:<20}{operation}")

    print("=" * 70 + "\n")


def save_results_to_json(results: list[dict], output_path: str) -> None:
    """
    将分析结果保存到 JSON 文件

    Args:
        results: 分析结果列表
        output_path: 输出文件路径
    """
    output = {
        "生成时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "分析系统": "7维度选股Agent（LangGraph多Agent架构）",
        "分析股票数量": len(results),
        "分析结果": results,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n分析结果已保存至：{output_path}")


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="A股选股分析系统 - 7维度LangGraph多Agent架构",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
7个选股条件：
  条件一：新政策支持行业（权重20%）
  条件二：行业龙头企业（权重15%）
  条件三：股东结构私募+个人>60%（权重15%）
  条件四：产品涨价+供需不平衡（权重20%）
  条件五：未来半年~2年上涨趋势（权重10%）
  条件六：转折催化剂事件（权重10%）
  条件七：技术量能突破（权重10%）

使用示例：
  python main.py 000001                           # 分析平安银行
  python main.py 000001 600519                    # 分析平安银行和贵州茅台
  python main.py --output report.json 000001 600519  # 保存结果到文件
  python main.py --concurrent 2 000001 600519 300750  # 最多2个并发
        """,
    )

    parser.add_argument(
        "stock_codes",
        nargs="+",
        help="A股股票代码，可以输入多个（如：000001 600519 300750）",
    )

    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="将分析结果保存为JSON文件（如：report.json）",
    )

    parser.add_argument(
        "--concurrent", "-c",
        type=int,
        default=2,
        help="批量分析时的最大并发数（默认：2，避免API限流）",
    )

    parser.add_argument(
        "--no-print",
        action="store_true",
        help="不打印详细报告（仅保存到文件，需配合 --output 使用）",
    )

    return parser.parse_args()


async def main() -> None:
    """主函数"""
    args = parse_args()

    # 验证配置
    try:
        settings.validate()
    except ValueError as e:
        print(f"配置错误：{e}")
        print("\n请按以下步骤配置：")
        print("1. 复制 .env.example 为 .env 文件")
        print("2. 在 .env 文件中填写 DEEPSEEK_API_KEY")
        sys.exit(1)

    stock_codes = list(dict.fromkeys(args.stock_codes))  # 保持顺序去重
    invalid_codes = [code for code in stock_codes if not code.isdigit() or len(code) != 6]
    if invalid_codes:
        print(f"警告：以下股票代码格式可能不正确（应为6位数字）：{invalid_codes}")
        confirm = input("是否继续？(y/n): ").strip().lower()
        if confirm != "y":
            sys.exit(0)

    print(f"\n待分析股票：{', '.join(stock_codes)}（共 {len(stock_codes)} 只）")
    print(f"使用模型：{settings.deepseek.model_name}")
    print(f"分析维度：7个选股条件（政策/龙头/股东/供需/趋势/催化剂/技术）")
    print(f"最大并发：{args.concurrent}")

    # 执行分析
    if len(stock_codes) == 1:
        result = await run_stock_analysis(stock_codes[0])
        results = [result]
    else:
        print(f"\n开始批量分析 {len(stock_codes)} 只股票...")
        results = await run_batch_analysis(stock_codes, max_concurrent=args.concurrent)

    # 输出报告
    if not args.no_print:
        for result in results:
            print_analysis_report(result)

        if len(results) > 1:
            print_batch_summary(results)

    # 保存到文件
    if args.output:
        save_results_to_json(results, args.output)
    elif args.no_print:
        default_output = f"stock_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        save_results_to_json(results, default_output)


if __name__ == "__main__":
    asyncio.run(main())
