# ui/animations.py

class Blinker:
    """
    Simple background blinker for a Tk Label widget.
    Use start() and stop() from the main thread.
    """
    def __init__(self, widget, on_color=None, off_color=None, interval_ms=500):
        self.widget = widget
        self.on_color = on_color or "orange"
        self.off_color = off_color or widget.cget("foreground") or "black"
        self.interval = interval_ms
        self._running = False
        self._state = False

    def _tick(self):
        if not self._running:
            return
        self._state = not self._state
        color = self.on_color if self._state else self.off_color
        try:
            self.widget.config(foreground=color)
        except Exception:
            pass
        # schedule next
        self.widget.after(self.interval, self._tick)

    def start(self):
        if self._running:
            return
        self._running = True
        self._state = False
        self._tick()

    def stop(self):
        self._running = False
        try:
            self.widget.config(foreground=self.off_color)
        except Exception:
            pass
