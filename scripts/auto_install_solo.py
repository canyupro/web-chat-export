"""
DeepSeek Chat Export Skill - 自动安装到 SOLO
自动检测并安装到正确的 SOLO 技能目录
"""

import os
import sys
import shutil
from pathlib import Path
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def find_solo_skill_dirs() -> list:
    """
    自动查找所有可能的 SOLO 技能目录
    """
    skill_dirs = []
    home = Path.home()
    
    # 可能的根目录
    possible_roots = [
        home / ".trae-cn",
        home / ".trae",
        home / ".config" / "trae",
        home / ".config" / "trae-cn",
    ]
    
    # 在每个根目录下查找 skills 文件夹
    for root in possible_roots:
        if root.exists():
            # 查找所有 skills 目录
            for skills_dir in root.rglob("skills"):
                if skills_dir.is_dir():
                    skill_dirs.append(skills_dir)
    
    # 去重并保持顺序
    seen = set()
    unique_dirs = []
    for d in skill_dirs:
        if d not in seen:
            seen.add(d)
            unique_dirs.append(d)
    
    return unique_dirs


def get_source_files() -> dict:
    """
    获取需要安装的文件列表（值可以是文件或目录路径）
    """
    base_dir = Path(__file__).resolve().parents[1]
    
    files = {
        "SKILL.md": base_dir / ".trae" / "skills" / "web-chat-export" / "SKILL.md",
        "deepseek_export.py": base_dir / "deepseek_export.py",
        "models.py": base_dir / "models.py",
        "exporters": base_dir / "exporters",
        "README.md": base_dir / "README.md",
        ".env.example": base_dir / ".env.example",
    }
    
    return files


def install_to_solo_skill_dir(target_dir: Path, files: dict) -> bool:
    """
    安装 Skill 到指定的 SOLO 技能目录
    """
    skill_name = "web-chat-export"
    skill_dir = target_dir / skill_name
    
    print(f"\n目标目录: {skill_dir}")
    
    try:
        # 创建技能目录
        skill_dir.mkdir(parents=True, exist_ok=True)
        
        # 复制文件（支持文件与目录）
        copied = []
        for filename, filepath in files.items():
            if filepath.exists():
                target_path = skill_dir / filename
                if filepath.is_dir():
                    shutil.copytree(filepath, target_path,
                                    dirs_exist_ok=True,
                                    ignore=shutil.ignore_patterns("__pycache__"))
                else:
                    shutil.copy2(filepath, target_path)
                copied.append(filename)
                print(f"  ✓ {filename}")
            else:
                print(f"  ⚠ 跳过 {filename} (不存在)")
        
        # 创建 __init__.py
        init_file = skill_dir / "__init__.py"
        init_file.write_text('"""DeepSeek Chat Export Skill for SOLO"""\n', encoding="utf-8")
        print(f"  ✓ __init__.py")
        
        return True
        
    except Exception as e:
        print(f"  ✗ 安装失败: {e}")
        return False


def verify_installation(skill_dir: Path) -> bool:
    """
    验证安装是否成功
    """
    required_files = ["SKILL.md", "deepseek_export.py", "models.py", "exporters", "__init__.py"]
    
    for filename in required_files:
        if not (skill_dir / filename).exists():
            print(f"  ✗ 缺少文件: {filename}")
            return False
    
    # 验证 SKILL.md 格式
    skill_md = skill_dir / "SKILL.md"
    content = skill_md.read_text(encoding="utf-8")
    
    if "---" not in content or "name:" not in content:
        print(f"  ✗ SKILL.md 格式无效")
        return False
    
    return True


def auto_install():
    """
    自动安装到所有找到的 SOLO 技能目录
    """
    print("=" * 70)
    print("DeepSeek Chat Export Skill - 自动安装到 SOLO")
    print("=" * 70)
    print(f"\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 查找技能目录
    print("\n[1/4] 查找 SOLO 技能目录...")
    skill_dirs = find_solo_skill_dirs()
    
    if not skill_dirs:
        print("  ✗ 未找到 SOLO 技能目录")
        print("\n可能的解决方案:")
        print("  1. 确保 SOLO 已安装并运行过至少一次")
        print("  2. 手动指定目录: python scripts/auto_install_solo.py --target-dir <路径>")
        return False
    
    print(f"  ✓ 找到 {len(skill_dirs)} 个技能目录:")
    for i, d in enumerate(skill_dirs, 1):
        print(f"    {i}. {d}")
    
    # 获取源文件
    print("\n[2/4] 检查源文件...")
    files = get_source_files()
    
    available_files = [f for f, p in files.items() if p.exists()]
    print(f"  ✓ 找到 {len(available_files)} 个文件:")
    for f in available_files:
        print(f"    - {f}")
    
    # 安装到每个目录
    print("\n[3/4] 开始安装...")
    installed = []
    failed = []
    
    for skill_dir in skill_dirs:
        print(f"\n安装到: {skill_dir}")
        if install_to_solo_skill_dir(skill_dir, files):
            installed.append(skill_dir)
        else:
            failed.append(skill_dir)
    
    # 验证安装
    print("\n[4/4] 验证安装...")
    verified = []
    for skill_dir in installed:
        skill_path = skill_dir / "web-chat-export"
        print(f"\n验证: {skill_path}")
        if verify_installation(skill_path):
            print("  ✓ 验证通过")
            verified.append(skill_path)
        else:
            print("  ✗ 验证失败")
    
    # 输出结果
    print("\n" + "=" * 70)
    print("安装结果")
    print("=" * 70)
    print(f"\n总目录数: {len(skill_dirs)}")
    print(f"安装成功: {len(installed)}")
    print(f"验证通过: {len(verified)}")
    print(f"安装失败: {len(failed)}")
    
    if verified:
        print("\n✓ Skill 已成功安装到以下位置:")
        for v in verified:
            print(f"  - {v}")
        print("\n使用方法:")
        print("  1. 重启 SOLO")
        print("  2. 在对话中提及 '导出 DeepSeek 对话' 即可触发此 Skill")
        return True
    else:
        print("\n✗ 安装失败，请检查错误信息")
        return False


def uninstall_from_all():
    """
    从所有 SOLO 技能目录卸载
    """
    print("=" * 70)
    print("DeepSeek Chat Export Skill - 卸载")
    print("=" * 70)
    
    skill_dirs = find_solo_skill_dirs()
    skill_name = "web-chat-export"
    
    removed = []
    for skill_dir in skill_dirs:
        target = skill_dir / skill_name
        if target.exists():
            try:
                shutil.rmtree(target)
                removed.append(target)
                print(f"✓ 已卸载: {target}")
            except Exception as e:
                print(f"✗ 卸载失败 {target}: {e}")
    
    print(f"\n共卸载 {len(removed)} 个位置")
    return len(removed) > 0


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="自动安装 DeepSeek Chat Export Skill 到 SOLO",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 自动安装到所有找到的 SOLO 目录
  python scripts/auto_install_solo.py
  
  # 卸载
  python scripts/auto_install_solo.py --uninstall
  
  # 仅查找目录，不安装
  python scripts/auto_install_solo.py --find-only
        """
    )
    
    parser.add_argument(
        "--uninstall", "-u",
        action="store_true",
        help="卸载 Skill"
    )
    parser.add_argument(
        "--find-only", "-f",
        action="store_true",
        help="仅查找 SOLO 目录，不安装"
    )
    parser.add_argument(
        "--target-dir", "-t",
        type=str,
        help="指定目标目录（覆盖自动查找）"
    )
    
    args = parser.parse_args()
    
    if args.uninstall:
        uninstall_from_all()
    elif args.find_only:
        print("查找 SOLO 技能目录...")
        dirs = find_solo_skill_dirs()
        print(f"\n找到 {len(dirs)} 个目录:")
        for d in dirs:
            print(f"  - {d}")
    elif args.target_dir:
        # 安装到指定目录
        target = Path(args.target_dir)
        files = get_source_files()
        install_to_solo_skill_dir(target, files)
    else:
        # 自动安装
        success = auto_install()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
