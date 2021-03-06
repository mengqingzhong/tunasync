#!/usr/bin/env python2
# -*- coding:utf-8 -*-
import sh
import sys
from setproctitle import setproctitle
import signal
import Queue


def run_job(sema, child_q, manager_q, provider, **settings):
    aquired = False
    setproctitle("tunasync-{}".format(provider.name))

    def before_quit(*args):
        provider.terminate()
        if aquired:
            print("{} release semaphore".format(provider.name))
            sema.release()
        sys.exit(0)

    signal.signal(signal.SIGTERM, before_quit)
    if provider.delay > 0:
        try:
            msg = child_q.get(timeout=provider.delay)
            if msg == "terminate":
                manager_q.put(("CONFIG_ACK", (provider.name, "QUIT")))
                return
        except Queue.Empty:
            pass

    max_retry = settings.get("max_retry", 1)
    while 1:
        try:
            sema.acquire(True)
        except:
            break
        aquired = True

        ctx = {}   # put context info in it
        ctx['current_dir'] = provider.local_dir
        ctx['mirror_name'] = provider.name
        status = "pre-syncing"
        manager_q.put(("UPDATE", (provider.name, status, ctx)))

        try:
            for hook in provider.hooks:
                hook.before_job(provider=provider, ctx=ctx)
        except Exception:
            import traceback
            traceback.print_exc()
            status = "fail"
        else:
            status = "syncing"
            for retry in range(max_retry):
                manager_q.put(("UPDATE", (provider.name, status, ctx)))
                print("start syncing {}, retry: {}".format(provider.name, retry))
                provider.run(ctx=ctx)

                status = "success"
                try:
                    provider.wait()
                except sh.ErrorReturnCode:
                    status = "fail"

                if status == "success":
                    break

        try:
            for hook in provider.hooks[::-1]:
                hook.after_job(provider=provider, status=status, ctx=ctx)
        except Exception:
            import traceback
            traceback.print_exc()
            status = "fail"

        sema.release()
        aquired = False

        print("syncing {} finished, sleep {} minutes for the next turn".format(
            provider.name, provider.interval
        ))

        manager_q.put(("UPDATE", (provider.name, status, ctx)))

        try:
            msg = child_q.get(timeout=provider.interval * 60)
            if msg == "terminate":
                manager_q.put(("CONFIG_ACK", (provider.name, "QUIT")))
                break
        except Queue.Empty:
            pass


# vim: ts=4 sw=4 sts=4 expandtab
