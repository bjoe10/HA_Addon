"""Find a hung run: shortly before the add-on stops it, write where it is waiting.

The service sets HAUSAKKU_DUMP_AFTER (seconds) for each run. After that time
- `arm()` makes faulthandler print every thread's stack (shows a blocking call),
- `watch()` prints the coroutine stack of every asyncio task (shows an await that never returns).
Both go to stderr, which the run log keeps. Only code locations are printed, no values.
"""
import asyncio, faulthandler, os, sys


def seconds():
    try:return float(os.environ.get('HAUSAKKU_DUMP_AFTER',''))
    except ValueError:return None


def arm():
    s=seconds()
    if s and s>0:faulthandler.dump_traceback_later(s,exit=False,file=sys.stderr)


def await_chain(coro):
    """The coroutine frames from the task's top down to the innermost await (Task.print_stack shows only the top)."""
    lines=[]
    while coro is not None:
        frame=getattr(coro,'cr_frame',None) or getattr(coro,'gi_frame',None) or getattr(coro,'ag_frame',None)
        if frame is not None:
            lines.append(f'  {os.path.basename(frame.f_code.co_filename)}:{frame.f_lineno} in {frame.f_code.co_name}')
        nxt=getattr(coro,'cr_await',None) or getattr(coro,'gi_yieldfrom',None) or getattr(coro,'ag_await',None)
        if nxt is None:
            if frame is None:lines.append('  wartet auf '+type(coro).__name__)
            break
        coro=nxt
    return lines


async def watch(stage=None):
    s=seconds()
    if not s or s<=0:return
    await asyncio.sleep(s)
    print(f'--- Lauf hängt seit {int(s)} s'+(f', Schritt: {stage[0]}' if stage and stage[0] else '')+' ---',file=sys.stderr,flush=True)
    for task in asyncio.all_tasks():
        if task is asyncio.current_task():continue
        print('Task '+task.get_name()+':',file=sys.stderr)
        for line in await_chain(task.get_coro()):print(line,file=sys.stderr)
    sys.stderr.flush()


def start_watch(stage=None):
    """Start the watcher in the running loop; the caller keeps the task (asyncio.run cancels it at the end)."""
    return asyncio.get_running_loop().create_task(watch(stage))
