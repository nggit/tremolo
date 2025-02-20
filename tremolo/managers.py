# Copyright (c) 2023 nggit

__all__ = ('ProcessManager',)

import multiprocessing as mp  # noqa: E402
import os  # noqa: E402
import signal  # noqa: E402

from threading import Thread  # noqa: E402

PARENT = 0
CHILD = 1


def sigterm_handler(signum, frame):
    raise KeyboardInterrupt


class ProcessManager:
    processes = {}

    @classmethod
    def _wait_main(cls, conn):
        while True:
            try:
                if conn.poll(1):
                    conn.recv()
            except EOFError:  # parent has exited
                os._exit(0)
                break
            except OSError:  # handle is closed
                break

    @classmethod
    def _target(cls, conn, func, *args, **kwargs):
        conn[PARENT].close()

        t = Thread(target=cls._wait_main, args=(conn[CHILD],))
        t.start()

        try:
            conn[CHILD].send(os.getpid())  # started, send pid to parent

            func(*args, **kwargs)
        except KeyboardInterrupt:
            pass
        finally:
            conn[CHILD].close()  # trigger handle is closed, also notify parent
            t.join()

    def spawn(self, target, args=(), kwargs={}, name=None, exit_cb=None):
        conn = mp.Pipe()
        process = mp.Process(target=self._target, name=name,
                             args=(conn, target, *args), kwargs=kwargs)
        process.start()
        conn[CHILD].close()

        self.processes[process.name] = {
            'target': target,
            'args': args,
            'kwargs': kwargs,
            'exit_cb': exit_cb,
            'parent_conn': conn[PARENT],
            'process': process
        }
        # block until the child starts, receive its pid
        return conn[PARENT].recv()

    def wait(self, timeout=30):
        signal.signal(signal.SIGTERM, sigterm_handler)

        while self.processes:
            try:
                connections = [info['parent_conn'] for info in
                               self.processes.values()]
                for conn in mp.connection.wait(connections):
                    # a child has exited, clean up
                    # there is no need to call recv() since EOF is expected
                    for name in self.processes:
                        if self.processes[name]['parent_conn'] is conn:
                            info = self.processes.pop(name)

                            info['process'].join()
                            conn.close()

                            if callable(info['exit_cb']):
                                info['exit_cb'](**info)

                            break
            except KeyboardInterrupt:
                while self.processes:
                    _, info = self.processes.popitem()
                    process = info['process']

                    try:
                        os.kill(process.pid, signal.SIGINT)
                        process.join(timeout)
                    except (OSError, KeyboardInterrupt):
                        print('pid %d terminated (forced quit)' % process.pid)
                    finally:
                        info['parent_conn'].close()

                    if process.exitcode == 0 and callable(info['exit_cb']):
                        info['exit_cb'](**info)
