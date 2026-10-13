#!/usr/bin/env bash
# third_party/OpenPLC_v3 (サブモジュール) をビルドする。
#   ./scripts/setup_openplc.sh
# 依存パッケージを apt で入れるため sudo のパスワードを聞かれます。所要時間は 5〜15 分程度。
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPENPLC_DIR="${OPENPLC_DIR:-$REPO_DIR/third_party/OpenPLC_v3}"

if [ ! -f "$OPENPLC_DIR/install.sh" ]; then
    echo "[setup] サブモジュールを取得します"
    git -C "$REPO_DIR" submodule update --init third_party/OpenPLC_v3
fi

# OpenPLC のインストーラは sudo を使う。root だけのコンテナでは sudo を入れておく
if ! command -v sudo >/dev/null 2>&1; then
    if [ "$(id -u)" -eq 0 ]; then
        apt-get update && apt-get install -y sudo
    else
        echo "[setup] sudo が必要です" >&2
        exit 1
    fi
fi

echo "[setup] OpenPLC_v3 をビルドします: $OPENPLC_DIR"
cd "$OPENPLC_DIR"
./install.sh linux

if [ ! -x "$OPENPLC_DIR/webserver/core/openplc" ]; then
    echo "[setup] OpenPLC のビルドに失敗しました。$OPENPLC_DIR/install_log.txt を確認してください" >&2
    exit 1
fi
# インストーラは pip の失敗では止まらないので、Web サーバに必要なモジュールを確認する
if ! "$OPENPLC_DIR/.venv/bin/python3" -c "import flask, flask_login, serial, pymodbus" 2>/dev/null; then
    echo "[setup] OpenPLC の Python パッケージのインストールに失敗しました (ネットワーク / プロキシを確認してください)" >&2
    echo "        ネットワークを確認してから、このスクリプトをもう一度実行してください" >&2
    exit 1
fi

# インストーラは OS 起動時に OpenPLC を自動起動するサービスを登録する。
# このリポジトリでは ros2 launch から起動するので、ポートが重ならないよう無効にする
if [ -d /run/systemd/system ] && systemctl list-unit-files openplc.service >/dev/null 2>&1; then
    echo "[setup] openplc サービスの自動起動を無効にします (ros2 launch から起動するため)"
    sudo systemctl disable --now openplc.service || true
fi

cat <<MSG

[setup] 完了しました。次のように環境変数を設定しておくと launch で指定を省略できます:
    echo 'export OPENPLC_DIR=$OPENPLC_DIR' >> ~/.bashrc
MSG
