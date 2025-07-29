#!/bin/bash
set -euo pipefail

BUILD_START_TS=$(date '+%Y-%m-%d %H:%M:%S')
echo "[build.sh] Build started at: $BUILD_START_TS"

trap 'code=$?; BUILD_END_TS=$(date "+%Y-%m-%d %H:%M:%S"); echo "[build.sh] Build failed at: $BUILD_END_TS (exit code $code)"; exit $code' ERR
trap 'BUILD_END_TS=$(date "+%Y-%m-%d %H:%M:%S"); echo "[build.sh] Build finished at: $BUILD_END_TS"' EXIT

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KERNEL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
OUT_DIR="${KERNEL_DIR}/out"
PATCHES_DIR="${SCRIPT_DIR}/patches"
CPU_CORES=$(nproc)

kernel_base_name="niigo_kernel"
DEFCONFIG="blossom_defconfig"

KSU_NEXT_DIR="${KERNEL_DIR}/KernelSU-Next"
KSU_DIR="${KERNEL_DIR}/KernelSU"

if [ -d "$KSU_NEXT_DIR" ]; then
    KSU_next_ver=$(cd "$KSU_NEXT_DIR" && git rev-list --count HEAD)
    KSU_ver=$((12700 + KSU_next_ver))
    kernel_name="${kernel_base_name}_ksu-next_${KSU_ver}"
elif [ -d "$KSU_DIR" ]; then
    KSU_git_ver=$(cd "$KSU_DIR" && git rev-list --count HEAD)
    KSU_ver=$((10000 + 200 + KSU_git_ver))
    kernel_name="${kernel_base_name}_ksu_${KSU_ver}"
else
    KSU_ver="none"
    kernel_name="${kernel_base_name}_no_ksu_$(date +%Y%m%d)"
fi

echo "KSU version: $KSU_ver"
echo "SUSFS version: 1.5.5"
echo "Starting kernel module build for: $kernel_name"

echo "Using kernel name: $kernel_name"

echo "Checking dependencies..."
command -v clang >/dev/null 2>&1 || { echo >&2 "Error: clang not found!"; exit 1; }
command -v aarch64-linux-gnu-gcc >/dev/null 2>&1 || { echo >&2 "Error: aarch64 toolchain not found!"; exit 1; }

echo "Cleaning previous build..."
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

export ARCH=arm64
export CROSS_COMPILE=aarch64-linux-gnu-
export CROSS_COMPILE_ARM32=arm-linux-gnueabi-
export CC=clang
export CLANG_TRIPLE=aarch64-linux-gnu-
export LLVM=1

if [ -d "$PATCHES_DIR" ]; then
    echo "Applying patches from: $PATCHES_DIR"
    cd "$KERNEL_DIR"
    for patch_file in "$PATCHES_DIR"/*.patch; do
        patch_name=$(basename "$patch_file")
        echo "Applying: $patch_name"
        if patch -p1 --forward --dry-run < "$patch_file" >/dev/null 2>&1; then
            if patch -p1 --forward < "$patch_file"; then
                echo "Applied: $patch_name"
            else
                echo "Failed to apply: $patch_name"
                exit 1
            fi
        else
            echo "Already applied: $patch_name"
        fi
    done
else
    echo "No patches directory found at $PATCHES_DIR, skipping..."
fi

echo "Configuring kernel..."
cd "$KERNEL_DIR"
make O="$OUT_DIR" $DEFCONFIG

config_file="$OUT_DIR/.config"
if grep -q '^CONFIG_LOCALVERSION=' "$config_file"; then
    sed -i "s/^CONFIG_LOCALVERSION=.*/CONFIG_LOCALVERSION=\"-${kernel_name}\"/" "$config_file"
else
    echo "CONFIG_LOCALVERSION=\"-${kernel_name}\"" >> "$config_file"
fi

echo "CONFIG_LOCALVERSION set to: $(grep 'CONFIG_LOCALVERSION=' ${config_file})"
echo "includes KernelSU version $KSU_ver" >> "${OUT_DIR}/banner_append"

echo "Optimizing config..."
"$KERNEL_DIR/scripts/config" --file "$OUT_DIR/.config" \
    --disable DEBUG_INFO \
    --enable STACKPROTECTOR \
    --set-val LTO_NONE y

echo "Building kernel with $CPU_CORES cores..."
cd "$OUT_DIR"
time make -j$CPU_CORES

if [ -f "$OUT_DIR/arch/arm64/boot/Image" ]; then
    echo -e "\nKernel build successful!"
    echo "Kernel image: $OUT_DIR/arch/arm64/boot/Image"
    echo "Size: $(du -h "$OUT_DIR/arch/arm64/boot/Image" | cut -f1)"
else
    echo -e "\nKernel build failed!"
    exit 1
fi
