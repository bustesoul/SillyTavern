#!/usr/bin/env python3

# # 进入 SillyTavern 根目录（能看到 public/）
# python3 swipe_patch.py apply
#
# # 回滚
# python3 swipe_patch.py revert

import re
import sys
import shutil
from pathlib import Path
from datetime import datetime

ROOT = Path('.').resolve()
SCRIPT_JS = ROOT / 'public' / 'script.js'
STYLE_CSS = ROOT / 'public' / 'style.css'
BACKUP_DIR = ROOT / '.swipe_patch_backup'
MARKER = '/* SWIPE_PATCH_APPLIED */'


def die(msg):
    print(f'[FATAL] {msg}')
    sys.exit(1)


def backup_file(p: Path):
    BACKUP_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    bk = BACKUP_DIR / f'{p.name}.{ts}.bak'
    shutil.copy2(p, bk)
    print(f'[BACKUP] {bk}')


def latest_backup(name: str):
    files = sorted(BACKUP_DIR.glob(f'{name}.*.bak'))
    return files[-1] if files else None


def require_contains(text: str, needle: str, where: str):
    if needle not in text:
        die(f'anchor not found in {where}: {needle}')


def replace_once_or_fail(text: str, old: str, new: str, where: str) -> str:
    if old in text:
        return text.replace(old, new, 1)
    die(f'expected block not found in {where}: {old[:120]!r}...')


def apply_script_js(text: str) -> str:
    if MARKER in text:
        print('[SKIP] script.js already patched')
        return text

    # 1) 允许生成期间进行左滑浏览（移除全局生成禁用）
    gate_line = '        //Cannot swipe while generating.\n        !isGenerating() &&\n'
    if gate_line in text:
        text = text.replace(gate_line, '', 1)

    # 2) 旧消息也可滑动（移除“仅最后一条消息可滑动”）
    old_last_only = '        //If the message is the last message, and it exists.\n        (messageId == chat.length - 1) &&\n'
    if old_last_only in text:
        text = text.replace(old_last_only, '', 1)

    # 3) 旧消息 overswipe 行为固定 LOOP（只浏览，不重试）
    anchor = "    //Small System messages can't be swiped.\n    else if (message?.extra?.isSmallSys) return OVERSWIPE_BEHAVIOR.NONE;\n"
    require_contains(text, anchor, 'script.js')
    historic_line = '    // Historic messages should only browse existing swipes, never trigger regeneration.\n    else if (messageId !== chat.length - 1) return OVERSWIPE_BEHAVIOR.LOOP;\n'
    if historic_line not in text:
        text = text.replace(anchor, anchor + historic_line, 1)

    # 4) 生成中右滑限制：仅限制“最新消息”右滑
    patterns = [
        (
            r"if \(isGenerating\(\) && direction !== SWIPE_DIRECTION\.LEFT && \(swipes && !swipesHidden && \(swipeState === SWIPE_STATE\.NONE\)\)\) \{\n"
            r"\s*toastr\.warning\(t`Cannot swipe while generating\. Stop the request and try again\.`, t`Swipe aborted`\);",
            "if (isGenerating() && direction !== SWIPE_DIRECTION.LEFT && mesId === chat.length - 1 && (swipes && !swipesHidden && (swipeState === SWIPE_STATE.NONE))) {\n"
            "            toastr.warning(t`Cannot swipe right on the latest message while generating. Stop the request and try again.`, t`Swipe aborted`);",
        ),
        (
            r"if \(isGenerating\(\) && direction !== SWIPE_DIRECTION\.LEFT && \(swipes && !swipesHidden && \(swipeState === SWIPE_STATE\.NONE\)\)\) \{\n"
            r"\s*toastr\.warning\(t`Cannot swipe right while generating\. Stop the request and try again\.`, t`Swipe aborted`\);",
            "if (isGenerating() && direction !== SWIPE_DIRECTION.LEFT && mesId === chat.length - 1 && (swipes && !swipesHidden && (swipeState === SWIPE_STATE.NONE))) {\n"
            "            toastr.warning(t`Cannot swipe right on the latest message while generating. Stop the request and try again.`, t`Swipe aborted`);",
        ),
    ]

    replaced_guard = False
    for pat, repl in patterns:
        text_new, n = re.subn(pat, repl, text, count=1)
        if n:
            text = text_new
            replaced_guard = True
            break

    # 如果已是目标状态则不报错
    if not replaced_guard:
        expected_guard = 'if (isGenerating() && direction !== SWIPE_DIRECTION.LEFT && mesId === chat.length - 1'
        if expected_guard not in text:
            die('failed to patch generation right-swipe guard in script.js')

    # 5) 让任意消息的箭头可点击
    text = text.replace(
        "$(document).on('click', '.last_mes .swipe_right', async (e, data) => await swipe(e, SWIPE_DIRECTION.RIGHT, data));",
        "$(document).on('click', '.mes .swipe_right', async (e, data) => await swipe(e, SWIPE_DIRECTION.RIGHT, data));",
        1,
    )
    text = text.replace(
        "$(document).on('click', '.last_mes .swipe_left', async (e, data) => await swipe(e, SWIPE_DIRECTION.LEFT, data));",
        "$(document).on('click', '.mes .swipe_left', async (e, data) => await swipe(e, SWIPE_DIRECTION.LEFT, data));",
        1,
    )

    # 如果两行都不存在，说明版本不匹配（或已改动）
    if ".last_mes .swipe_right" in text or ".last_mes .swipe_left" in text:
        # 至少有一行没成功替换，强制报错避免半补丁
        die('failed to patch swipe click handlers in script.js')

    return text + '\n' + MARKER + '\n'


def apply_style_css(text: str) -> str:
    if MARKER in text:
        print('[SKIP] style.css already patched')
        return text

    # Remove exactly the selector line:
    target = 'body:not(.swipeAllMessages) .mes:not(.last_mes) :is(.swipe_left, .swipe_right, .swipes-counter),'
    require_contains(text, target, 'style.css')
    text = text.replace(target + '\n', '', 1)

    return text + '\n' + MARKER + '\n'


def apply():
    if not SCRIPT_JS.exists() or not STYLE_CSS.exists():
        die('public/script.js or public/style.css not found')

    backup_file(SCRIPT_JS)
    backup_file(STYLE_CSS)

    SCRIPT_JS.write_text(apply_script_js(SCRIPT_JS.read_text(encoding='utf-8')), encoding='utf-8')
    STYLE_CSS.write_text(apply_style_css(STYLE_CSS.read_text(encoding='utf-8')), encoding='utf-8')

    print('[OK] swipe patch applied')


def revert():
    if not BACKUP_DIR.exists():
        die('no backup dir found')

    for p in (SCRIPT_JS, STYLE_CSS):
        bk = latest_backup(p.name)
        if not bk:
            die(f'no backup for {p.name}')
        shutil.copy2(bk, p)
        print(f'[RESTORE] {p} <= {bk}')

    print('[OK] swipe patch reverted')


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in ('apply', 'revert'):
        print('Usage: python3 swipe_patch.py apply|revert')
        sys.exit(1)
    if sys.argv[1] == 'apply':
        apply()
    else:
        revert()
