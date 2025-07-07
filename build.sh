#!/bin/bash
set -euo pipefail

maindir="$(cd "$(dirname "$0")" && pwd)"
patchesdir="${maindir}/patches"

# Применяем все патчи из папки patches
for patch_file in "$patchesdir"/*.patch; do
  echo "Applying patch: $(basename "$patch_file")"
  patch -p1 < "$patch_file"
done

# Сборка ядра
export ARCH=arm64
export CC=clang
export CROSS_COMPILE=aarch64-linux-gnu-
export CROSS_COMPILE_ARM32=arm-linux-gnueabi-

OUT_DIR="${maindir}/out"
DEFCONFIG="blossom_defconfig"

mkdir -p "$OUT_DIR"

echo "Configuring kernel..."
make O="$OUT_DIR" ARCH=arm64 CC=clang "$DEFCONFIG"

echo "Building kernel..."
make O="$OUT_DIR" ARCH=arm64 CC=clang \
  CROSS_COMPILE=aarch64-linux-gnu- \
  CROSS_COMPILE_ARM32=arm-linux-gnueabi- \
  AR=llvm-ar NM=llvm-nm OBJCOPY=llvm-objcopy \
  OBJDUMP=llvm-objdump STRIP=llvm-strip LD=ld.lld LLVM_IAS=1 -j"$(nproc)"

echo "Build finished!"
