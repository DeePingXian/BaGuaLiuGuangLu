import sys

class BadApple:
    def __init__(self):
        self.framesPerSecond = 10
        self.frameAmount = 2158

    def get_frame(self, i):
        if i >= self.frameAmount:
            return None
        pkg = __name__
        modName = f"{pkg}.frame{i}"
        __import__(modName)
        frame = memoryview(sys.modules[modName].frame)
        del sys.modules[modName]
        return frame