import tkinter as tk
from tkinter import ttk
from typing import Optional

from core.gui.themes import Styles


class CanvasTooltip:
    """
    It creates a tooltip for a given canvas tag or id as the mouse is
    above it.

    This class has been derived from the original Tooltip class updated
    and posted back to StackOverflow at the following link:

    https://stackoverflow.com/questions/3221956/
           what-is-the-simplest-way-to-make-tooltips-in-tkinter/
           41079350#41079350

    Alberto Vassena on 2016.12.10.
    """

    def __init__(self, canvas, *, pad=(5, 3, 5, 3), waittime=400, wraplength=600):
        # in miliseconds, originally 500
        self.waittime = waittime
        # in pixels, originally 180
        self.wraplength = wraplength
        self.canvas = canvas
        self.text = tk.StringVar()
        self.pad = pad
        self.id = None
        self.tw = None

    def on_enter(self, event: Optional[tk.Event] = None):
        self.schedule()

    def on_leave(self, event: Optional[tk.Event] = None):
        self.unschedule()
        self.hide()

    def schedule(self):
        self.unschedule()
        self.id = self.canvas.after(self.waittime, self.show)

    def unschedule(self):
        id_ = self.id
        self.id = None
        if id_:
            self.canvas.after_cancel(id_)

    def show(self, event: Optional[tk.Event] = None):
        def tip_pos_calculator(canvas, label, *, tip_delta=(10, 5), pad=(5, 3, 5, 3)):
            c = canvas
            s_width, s_height = c.winfo_screenwidth(), c.winfo_screenheight()
            width, height = (
                pad[0] + label.winfo_reqwidth() + pad[2],
                pad[1] + label.winfo_reqheight() + pad[3],
            )
            mouse_x, mouse_y = c.winfo_pointerxy()
            x1, y1 = mouse_x + tip_delta[0], mouse_y + tip_delta[1]
            x2, y2 = x1 + width, y1 + height

            x_delta = x2 - s_width
            if x_delta < 0:
                x_delta = 0
            y_delta = y2 - s_height
            if y_delta < 0:
                y_delta = 0

            offscreen = (x_delta, y_delta) != (0, 0)
            if offscreen:
                if x_delta:
                    x1 = mouse_x - tip_delta[0] - width
                if y_delta:
                    y1 = mouse_y - tip_delta[1] - height
            offscreen_again = y1 < 0  # out on the top
            if offscreen_again:
                y1 = 0
            return x1, y1

        pad = self.pad
        canvas = self.canvas

        # creates a toplevel window
        self.tw = tk.Toplevel(canvas.master)

        # Leaves only the label and removes the app window
        self.tw.wm_overrideredirect(True)
        win = ttk.Frame(self.tw, style=Styles.tooltip_frame, padding=3)
        win.grid()
        label = ttk.Label(
            win,
            textvariable=self.text,
            wraplength=self.wraplength,
            style=Styles.tooltip,
        )
        label.grid(padx=(pad[0], pad[2]), pady=(pad[1], pad[3]), sticky=tk.NSEW)
        x, y = tip_pos_calculator(canvas, label, pad=pad)
        self.tw.wm_geometry("+%d+%d" % (x, y))

    def hide(self):
        if self.tw:
            self.tw.destroy()
        self.tw = None
