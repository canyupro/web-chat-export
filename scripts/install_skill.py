"""
DeepSeek Chat Export Skill 安装脚本
自动安装到 SOLO/Qclaw 技能目录
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


def get_skill_source_dir() -> Path:
    """获取 Skill 源目录"""
    return get_project_root() / ".trae" / "skills" / "web-chat-export"


def get_project_root() -> Path:
    """获取项目根目录"""
    return Path(__file__).resolve().parents[1]


def get_solo_skill_dir() -> Path:
    """获取 SOLO Skill 目标目录"""
    # 尝试多个可能的位置
    possible_paths = [
        Path.home() / ".trae" / "skills" / "web-chat-export",
        Path.home() / ".trae-cn" / "skills" / "web-chat-export",
        Path.home() / ".config" / "trae" / "skills" / "web-chat-export",
    ]
    
    # 检查环境变量
    if "SOLO_SKILL_DIR" in os.environ:
        return Path(os.environ["SOLO_SKILL_DIR"]) / "web-chat-export"
    
    # 返回第一个可写的路径
    for path in possible_paths:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            return path
        except PermissionError:
            continue
    
    # 默认返回第一个
    return possible_paths[0]


def install_skill():
    """安装 Skill 到 SOLO 目录"""
    print("=" * 60)
    print("DeepSeek Chat Export Skill 安装程序")
    print("=" * 60)
    
    source_dir = get_skill_source_dir()
    target_dir = get_solo_skill_dir()
    
    print(f"\n源目录: {source_dir}")
    print(f"目标目录: {target_dir}")
    
    # 检查源目录
    if not source_dir.exists():
        print(f"\n错误: 源目录不存在: {source_dir}")
        print("请确保在正确的目录运行此脚本")
        return False
    
    # 创建目标目录
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"\n错误: 无法创建目标目录: {e}")
        return False
    
    # 复制文件
    try:
        # 复制 SKILL.md
        skill_md_source = source_dir / "SKILL.md"
        skill_md_target = target_dir / "SKILL.md"
        
        if skill_md_source.exists():
            shutil.copy2(skill_md_source, skill_md_target)
            print(f"\n✓ 已复制: SKILL.md")
        else:
            print(f"\n✗ 未找到: SKILL.md")
            return False
        
        # 复制脚本文件
        script_source = get_project_root() / "deepseek_export.py"
        script_target = target_dir / "deepseek_export.py"
        
        if script_source.exists():
            shutil.copy2(script_source, script_target)
            print(f"✓ 已复制: deepseek_export.py")
        
        # 复制其他必要文件
        for filename in ["README.md", ".env.example"]:
            file_source = get_project_root() / filename
            file_target = target_dir / filename
            if file_source.exists():
                shutil.copy2(file_source, file_target)
                print(f"✓ 已复制: {filename}")
        
        # 创建 __init__.py
        init_file = target_dir / "__init__.py"
        init_file.write_text('"""DeepSeek Chat Export Skill"""\n', encoding="utf-8")
        print(f"✓ 已创建: __init__.py")
        
        print("\n" + "=" * 60)
        print("安装完成!")
        print("=" * 60)
        print(f"\nSkill 已安装到: {target_dir}")
        print("\n使用方法:")
        print("  1. 重启 SOLO/Qclaw")
        print("  2. 在对话中提及 '导出 DeepSeek 对话' 即可触发此 Skill")
        print("\n或直接运行脚本:")
        print(f"  python {script_target} --help")
        
        return True
        
    except Exception as e:
        print(f"\n错误: 安装失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def uninstall_skill():
    """卸载 Skill"""
    target_dir = get_solo_skill_dir()
    
    if target_dir.exists():
        try:
            shutil.rmtree(target_dir)
            print(f"已卸载: {target_dir}")
            return True
        except Exception as e:
            print(f"卸载失败: {e}")
            return False
    else:
        print(f"Skill 未安装: {target_dir}")
        return False


def check_installation():
    """检查安装状态"""
    target_dir = get_solo_skill_dir()
    skill_md = target_dir / "SKILL.md"
    
    print("=" * 60)
    print("DeepSeek Chat Export Skill 状态检查")
    print("=" * 60)
    
    print(f"\n目标目录: {target_dir}")
    print(f"目录存在: {'是' if target_dir.exists() else '否'}")
    
    if target_dir.exists():
        print(f"\n文件列表:")
        for item in target_dir.iterdir():
            print(f"  - {item.name}")
    
    print(f"\nSKILL.md 存在: {'是' if skill_md.exists() else '否'}")
    
    if skill_md.exists():
        content = skill_md.read_text(encoding="utf-8")
        if "name:" in content:
            print("SKILL.md 格式: 有效")
        else:
            print("SKILL.md 格式: 无效")
    
    return target_dir.exists() and skill_md.exists()


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="DeepSeek Chat Export Skill 安装程序"
    )
    parser.add_argument(
        "--uninstall", "-u",
        action="store_true",
        help="卸载 Skill"
    )
    parser.add_argument(
        "--check", "-c",
        action="store_true",
        help="检查安装状态"
    )
    
    args = parser.parse_args()
    
    if args.uninstall:
        uninstall_skill()
    elif args.check:
        check_installation()
    else:
        install_skill()


if __name__ == "__main__":
    main()
