#!/bin/bash
set -euo pipefail

maindir="$(cd "$(dirname "$0")" && pwd)"

kernel_base_name="niigo_kernel"
defconfig_file="arch/arm64/configs/blossom_defconfig"

if [ -d "KernelSU-Next" ]; then
    KSU_next_ver=$(cd KernelSU-Next && git rev-list --count HEAD)
    KSU_ver=$((12700 + KSU_next_ver))
    kernel_name="${kernel_base_name}_ksu-next_${KSU_ver}"
elif [ -d "KernelSU" ]; then
    KSU_git_ver=$(cd KernelSU && git rev-list --count HEAD)
    KSU_ver=$((10000 + 200 + KSU_git_ver))
    kernel_name="${kernel_base_name}_ksu_${KSU_ver}"
else
    kernel_name="${kernel_base_name}_no_ksu_$(date +%Y%m%d)"
fi

echo "Using kernel name: $kernel_name"

patchesdir="${maindir}/patches"
for patch_file in "$patchesdir"/*.patch ; do
  patch -p1 < "$patch_file"
done

sed -i "s/\(CONFIG_LOCALVERSION=\)\(.*\)/\1\"-${kernel_name}\"/" "${defconfig_file}"

echo "$(grep 'CONFIG_LOCALVERSION=' ${defconfig_file})"
echo "includes KernelSU version $KSU_ver" >> banner_append
