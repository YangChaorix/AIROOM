#!/bin/bash
# setup.sh - 一键初始化 xhs-agent 环境
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
CRED_DIR="$HOME/.openclaw/credentials"
CRED_FILE="$CRED_DIR/xhs.json"

echo "🚀 初始化 xhs-agent..."

# 创建虚拟环境
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 创建 Python 虚拟环境..."
    python3 -m venv "$VENV_DIR"
fi

# 安装依赖
echo "📥 安装依赖..."
"$VENV_DIR/bin/pip" install -q -r "$SCRIPT_DIR/requirements.txt"

# 创建 credentials 占位文件
mkdir -p "$CRED_DIR"
if [ ! -f "$CRED_FILE" ] || grep -q "PLACEHOLDER" "$CRED_FILE"; then
    echo "🔑 创建凭证占位文件..."
    cat > "$CRED_FILE" << 'EOF'
{
  "a1": "PLACEHOLDER_a1",
  "web_session": "PLACEHOLDER_web_session"
}
EOF
    echo "⚠️  请编辑 $CRED_FILE，填入真实的 Cookie 值"
else
    echo "✅ 凭证文件已存在"
fi

# 创建 images 目录
mkdir -p "$SCRIPT_DIR/images"

echo ""
echo "✅ 初始化完成！"
echo ""
echo "下一步："
echo "  1. 编辑 $CRED_FILE，填写 a1 和 web_session"
echo "  2. 编辑 $SCRIPT_DIR/config/settings.json，设置账号风格"
echo "  3. 测试运行：$VENV_DIR/bin/python $SCRIPT_DIR/run.py --dry-run"
