import webview
import time
import threading

def on_start(window):
    print("Initial hidden state:", getattr(window, 'hidden', 'NO_SUCH_ATTRIBUTE'))
    print("Initial is_minimized state:", getattr(window, 'is_minimized', 'NO_SUCH_ATTRIBUTE'))
    
    print("Calling hide()...")
    window.hide()
    time.sleep(1)
    
    print("After hide, hidden state:", getattr(window, 'hidden', 'NO_SUCH_ATTRIBUTE'))
    
    print("Calling show()...")
    window.show()
    time.sleep(1)
    
    print("After show, hidden state:", getattr(window, 'hidden', 'NO_SUCH_ATTRIBUTE'))
    window.destroy()

def test_webview_hidden_suite():
    window = webview.create_window('Test', html='<h1>Test</h1>')
    webview.start(on_start, window)

if __name__ == '__main__':
    test_webview_hidden_suite()
