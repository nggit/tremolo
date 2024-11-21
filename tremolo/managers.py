# Copyright (c) 2023 nggit

import multiprocessing as mp
import os
import signal

from threading import Thread


def sigterm_handler(signum, frame):
    raise KeyboardInterrupt


class ProcessManager:
    processes = {}

    def __init__(self):
        mp.set_start_method('spawn', force=True)

    @classmethod
    def _wait_main(cls, conn):
        while True:
            try:
                if conn.poll(1):
                    conn.recv()
                    continue
            except EOFError:  # parent has exited
                conn.close()
                os.kill(os.getpid(), signal.SIGTERM)
                return
            except OSError:  # handle is closed
                break

    @classmethod
    def _target(cls, conn, func, *args, **kwargs):
        t = Thread(target=cls._wait_main, args=(conn,))
        t.start()

        try:
            conn.send(os.getpid())  # started, send pid to parent

            return func(*args, **kwargs)
        finally:
            conn.close()  # trigger handle is closed
            t.join()

    def spawn(self, target, args=(), kwargs={}, name=None, exit_cb=None):
        parent_conn, child_conn = mp.Pipe()
        process = mp.Process(target=self._target, name=name,
                             args=(child_conn, target, *args), kwargs=kwargs)
        process.start()
        child_conn.close()

        self.processes[process.name] = {
            'target': target,
            'args': args,
            'kwargs': kwargs,
            'exit_cb': exit_cb,
            'parent_conn': parent_conn,
            'process': process
        }
        # block until the child starts, receive its pid
        return parent_conn.recv()

    def wait(self):
        signal.signal(signal.SIGTERM, sigterm_handler)

        while self.processes:
            try:
                connections = [info['parent_conn'] for info in
                               self.processes.values()]
                for conn in mp.connection.wait(connections):
                    # a child has exited, clean up
                    # there is no need to call recv() because EOF is expected
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

                    if info['process'].is_alive():
                        os.kill(info['process'].pid, signal.SIGTERM)

                    info['process'].join()
                    info['parent_conn'].close()

                    if callable(info['exit_cb']):
                        info['exit_cb'](**info)
