#!/bin/bash
# ============================================================
# SAGA - 一键安装依赖脚本
# 第 1 批 / 共 10 批
# 用途：在目标服务器上安装所有 Python 和 Node.js 依赖
# 使用：cd /home/jding/SAGA && bash scripts/setup.sh
# ============================================================

set -e  # 遇到错误立即停止

# 颜色定义（方便区分输出）
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # 无颜色

echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  SAGA - 环境安装脚本${NC}"
echo -e "${GREEN}  Synthetic Agentic Graph Architecture${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""

# --- 检测项目根目录 ---
# 脚本应从项目根目录运行，检查 config.py 是否存在
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

if [ ! -f "config.py" ]; then
    echo -e "${RED}[错误] 未找到 config.py，请确保从项目根目录运行此脚本${NC}"
    echo "  用法: cd /home/jding/SAGA && bash scripts/setup.sh"
    exit 1
fi

echo -e "${GREEN}[1/6] 项目根目录: $PROJECT_ROOT${NC}"

# --- 检查 Python 版本 ---
echo -e "${GREEN}[2/6] 检查 Python 版本...${NC}"
PYTHON_VERSION=$(python3 --version 2>&1)
echo "  $PYTHON_VERSION"

# 检查 Python 版本 >= 3.8
PYTHON_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PYTHON_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 8 ]); then
    echo -e "${RED}[错误] Python >= 3.8 is required, found $PYTHON_MAJOR.$PYTHON_MINOR${NC}"
    exit 1
fi

# --- 安装 Python 依赖 ---
echo -e "${GREEN}[3/6] 安装 Python 依赖...${NC}"
echo "  pip install -r requirements.txt"

# 服务器没有 sudo 权限，需要 --break-system-packages 或 --user
# 优先尝试 --break-system-packages（适用于 Debian/Ubuntu 的 externally managed 环境）
# 如果不支持则回退到 --user
if pip install --help 2>&1 | grep -q "break-system-packages"; then
    pip install -r requirements.txt --break-system-packages 2>&1 | tail -5
else
    pip install -r requirements.txt --user 2>&1 | tail -5
fi

echo -e "${GREEN}  Python 依赖安装完成${NC}"

# --- 验证关键 Python 包 ---
echo -e "${GREEN}[4/6] 验证关键 Python 包...${NC}"

# 逐个检查关键依赖
MISSING=""
python3 -c "import websockets" 2>/dev/null || MISSING="$MISSING websockets"
python3 -c "import aiohttp" 2>/dev/null || MISSING="$MISSING aiohttp"
python3 -c "import igraph" 2>/dev/null || MISSING="$MISSING python-igraph"
python3 -c "import numpy" 2>/dev/null || MISSING="$MISSING numpy"
python3 -c "import dotenv" 2>/dev/null || MISSING="$MISSING python-dotenv"

# orjson 是可选的（有回退方案），但建议安装
python3 -c "import orjson" 2>/dev/null && echo "  orjson: OK (C 加速 JSON)" || echo -e "  ${YELLOW}orjson: 未安装（可选，将使用标准 json 库）${NC}"

if [ -n "$MISSING" ]; then
    echo -e "${RED}[错误] 以下包安装失败:$MISSING${NC}"
    echo "  请手动安装: pip install$MISSING --break-system-packages"
    exit 1
fi

echo "  websockets: OK"
echo "  aiohttp: OK"
echo "  python-igraph: OK (C 底层图生成)"
echo "  numpy: OK"
echo "  python-dotenv: OK"

# --- 检查 .env 文件 ---
echo -e "${GREEN}[5/6] 检查 .env 文件...${NC}"
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo "  .env 文件不存在，从 .env.example 复制..."
        cp .env.example .env
        echo -e "  ${YELLOW}已创建 .env 文件，请根据需要修改配置${NC}"
    else
        echo -e "  ${YELLOW}.env 和 .env.example 均不存在，将使用默认配置${NC}"
    fi
else
    echo "  .env 文件已存在"
fi

# --- 检查 Node.js（前端依赖，第 7 批才需要）---
echo -e "${GREEN}[6/6] 检查 Node.js 环境（前端用，第 7 批才需要）...${NC}"

# 尝试加载 nvm（服务器上 Node 通过 nvm 安装）
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

if command -v node &> /dev/null; then
    NODE_VERSION=$(node --version)
    echo "  Node.js: $NODE_VERSION"
    NPM_VERSION=$(npm --version 2>/dev/null || echo "未找到")
    echo "  npm: $NPM_VERSION"

    # 如果前端目录下有 package.json，安装前端依赖
    if [ -f "frontend/package.json" ]; then
        echo "  安装前端依赖..."
        cd frontend && npm install && cd ..
        echo "  前端依赖安装完成"
    else
        echo "  前端 package.json 尚未创建（第 7 批）"
    fi
else
    echo -e "  ${YELLOW}Node.js 未找到。前端开发需要 Node.js，请安装后重新运行。${NC}"
    echo "  提示：如果通过 nvm 安装，请先运行："
    echo '    export NVM_DIR="$HOME/.nvm"'
    echo '    [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"'
fi

# --- 创建必要目录 ---
mkdir -p output
mkdir -p core
mkdir -p rag
mkdir -p utils

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  安装完成！${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "  验证命令："
echo '    python3 -c "from config import get_full_config; print(get_full_config())"'
echo ""
echo "  下一步："
echo "    第 2 批: 骨架生成 (core/skeleton.py)"
echo ""
