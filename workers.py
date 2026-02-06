from PyQt6.QtCore import QThread, pyqtSignal, QObject


class WorkerSignals(QObject):
    finished = pyqtSignal(object)
    error = pyqtSignal(Exception)


class BackgroundTask(QThread):
    def __init__(self, func, args, parent=None):
        super().__init__(parent)
        self.signals = WorkerSignals()
        self.func = func
        self.args = args

    def run(self):
        try:
            result = self.func(*self.args)
            self.signals.finished.emit(result)
        except Exception as e:
            self.signals.error.emit(e)


class TaskManager:
    def __init__(self, status_callback=None):
        self._tasks = {}
        self._status_callback = status_callback

    def run(self, task_id, func, args, on_success, on_error=None, status_msg=None):
        if status_msg and self._status_callback:
            self._status_callback(status_msg, busy=True)

        task = BackgroundTask(func, args)

        def on_finished(result):
            self._tasks.pop(task_id, None)
            if self._status_callback:
                self._status_callback("Ready", busy=False)
            on_success(result)

        def on_task_error(error):
            self._tasks.pop(task_id, None)
            if self._status_callback:
                self._status_callback(f"Error: {error}", busy=False)
            if on_error:
                on_error(error)

        task.signals.finished.connect(on_finished)
        task.signals.error.connect(on_task_error)
        self._tasks[task_id] = task
        task.start()

    def is_running(self, task_id):
        task = self._tasks.get(task_id)
        return task is not None and task.isRunning()

    def any_running(self):
        return any(t.isRunning() for t in self._tasks.values())
