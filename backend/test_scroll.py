import asyncio
from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import BufferControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.widgets import Frame

# 1. Read-only scrollable buffer for history
history_text = "\n".join([f"Line {i}: Claude Code style chat log entry showing scroll test..." for i in range(1, 100)])
history_buffer = Buffer(read_only=True)
history_buffer.set_document(Document(history_text, cursor_position=0), bypass_readonly=True)

history_window = Window(
    content=BufferControl(buffer=history_buffer),
    wrap_lines=True,
)

# 2. Input buffer
input_buffer = Buffer()
input_window = Window(
    content=BufferControl(buffer=input_buffer),
    height=3,
)
input_frame = Frame(input_window, title="Input (Type here, use mouse wheel to scroll top window)")

layout = Layout(
    HSplit([
        history_window,
        input_frame,
    ]),
    focused_element=input_window,
)

kb = KeyBindings()

@kb.add("c-c")
def _exit(event):
    event.app.exit()

# Global wheel interception routed directly to the scrollable buffer
@kb.add("<scroll-up>")
def _wheel_up(event):
    history_window.vertical_scroll = max(0, history_window.vertical_scroll - 3)

@kb.add("<scroll-down>")
def _wheel_down(event):
    history_window.vertical_scroll += 3

app = Application(
    layout=layout,
    key_bindings=kb,
    full_screen=True,
    mouse_support=True,
)

if __name__ == "__main__":
    app.run()