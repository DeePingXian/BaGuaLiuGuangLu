import machine, network, asyncio, gc, array, rp2, json, ubinascii, os, time, _thread, ina226, ssd1306, badapple, ntptime
from micropython import const

PROGRAM_VERSION = "25.07.07"
SUM_OF_INTERNAL_LEDS = const(27)
SHORT_PRESS_TIME = const(50)    #ms
LONG_PRESS_TIME = const(1000)
RELEASE_TIME = const(500)
SCREEN_REFRESH_INTERVAL = const(1000)
INA226_POSITIVE_CURRENT_COEFFICIENT = 0.999       #調整INA226誤差
INA226_NEGATIVE_CURRENT_COEFFICIENT = 0.9927
LOAD_INA226_INTERVAL = const(500)
ENABLE_INA226_OCP = const(1)
PICO_ADC_SINK_CURRENT = const(38)       #uA
NTP_SYNC_INTERVAL_HR = const(24)

ledButton = machine.Pin((6), machine.Pin.IN)
screenButton = machine.Pin((7), machine.Pin.IN)

settings = {}

def restore_default_settings(type=0):
    if type == 0:
        settings["wifi"] = {}
        settings["internalLed"] = {}
        settings["externalLed"] = {}
        settings["wifi"]["ssid"] = "BaGuaLu"
        settings["wifi"]["password"] = "bagualu123"
        settings["wifi"]["mode"] = 0
        settings["backgroundImageUrl"] = ""
        settings["internalLed"]["mode"] = 1     #0 關燈 1 單色開 2 單色閃 3 雷達 4 彩色循環 5 彩色流水
        settings["internalLed"]["color"] = [255, 160, 0]        #RGB format
        settings["internalLed"]["brightness"] = 100
        settings["internalLed"]["blinkInterval"] = 500
        settings["internalLed"]["sequentialStepInterval"] = 200
        settings["internalLed"]["sequentialDirection"] = True       #順時針亮起（否則逆時針）
        settings["internalLed"]["radarContrast"] = 80
        settings["internalLed"]["colorCycleTime"] = 5000
        settings["internalLed"]["rainbowColorStep"] = 13
        settings["externalLed"]["mode"] = 5     #0 關燈 1 單色開 2 單色閃 3 序列 4 彩色循環 5 彩色流水
        settings["externalLed"]["color"] = [255, 255, 255]
        settings["externalLed"]["brightness"] = 100
        settings["externalLed"]["blinkInterval"] = 500
        settings["externalLed"]["sequentialStepInterval"] = 200
        settings["externalLed"]["colorCycleTime"] = 5000
        settings["externalLed"]["rainbowColorStep"] = 10
        settings["externalLed"]["sumOfLeds"] = 30
    elif type == 1:
        settings["wifi"] = {}
        settings["internalLed"] = {}
        settings["externalLed"] = {}
        settings["wifi"]["ssid"] = "BaGuaLu"
        settings["wifi"]["password"] = "bagualu123"
        settings["wifi"]["mode"] = 0
        settings["backgroundImageUrl"] = ""
    elif type == 2:
        settings["internalLed"]["mode"] = 1
        settings["internalLed"]["color"] = [255, 160, 0]
        settings["internalLed"]["brightness"] = 100
        settings["internalLed"]["blinkInterval"] = 500
        settings["internalLed"]["sequentialStepInterval"] = 200
        settings["internalLed"]["sequentialDirection"] = True
        settings["internalLed"]["radarContrast"] = 80
        settings["internalLed"]["colorCycleTime"] = 5000
        settings["internalLed"]["rainbowColorStep"] = 13
    elif type == 3:
        settings["externalLed"]["mode"] = 5
        settings["externalLed"]["color"] = [255, 255, 255]
        settings["externalLed"]["brightness"] = 100
        settings["externalLed"]["blinkInterval"] = 500
        settings["externalLed"]["sequentialStepInterval"] = 200
        settings["externalLed"]["colorCycleTime"] = 5000
        settings["externalLed"]["rainbowColorStep"] = 10
        settings["externalLed"]["sumOfLeds"] = 30

    with open("./settings.json", "w", encoding="utf8") as f:
        json.dump(settings, f)

def load_settings():
    if not "settings.json" in os.listdir():
        restore_default_settings()
    global settings
    with open("./settings.json", "r", encoding="utf8") as f:
        settings = json.load(f)

def led_process():
    # https://github.com/raspberrypi/pico-micropython-examples/blob/master/pio/neopixel_ring/neopixel_ring.py
    # Raspberry Pi Pico 的PIO 程式，用於控制 WS2812B LED
    @rp2.asm_pio(sideset_init=rp2.PIO.OUT_LOW, out_shiftdir=rp2.PIO.SHIFT_LEFT, autopull=True, pull_thresh=24)
    def ws2812():
        T1 = 2
        T2 = 5
        T3 = 3
        wrap_target()
        label("bitloop")
        out(x, 1)               .side(0)    [T3 - 1]
        jmp(not_x, "do_zero")   .side(1)    [T1 - 1]
        jmp("bitloop")          .side(1)    [T2 - 1]
        label("do_zero")
        nop()                   .side(0)    [T2 - 1]
        wrap()

    class NeoPixel:
        def __init__(self, pin, ledSum, pioId, bpp=3, timing=1):
            self.ledSum = ledSum
            self.bpp = bpp
            self.pin = pin
            self.buf = array.array("I", [0] * ledSum)
            self.sm = rp2.StateMachine(pioId, ws2812, freq=8000000, sideset_base=pin)
            self.sm.active(1)

        def __len__(self):
            return self.ledSum

        def __getitem__(self, index):
            return ((self.buf[index]>>16)&0xFF, (self.buf[index]>>8)&0xFF, self.buf[index]&0xFF)

        def __setitem__(self, index, val):
            self.buf[index] = val[0]<<16 | val[1]<<8 | val[2]

        def write(self):
            # 將 RGB 資料轉換為 GRB，符合 WS2812B 的資料格式
            grb = array.array("I", [0] * self.ledSum)
            for i in range(self.ledSum):
                r = (self.buf[i]>>16) & 0xFF
                g = (self.buf[i]>>8) & 0xFF
                b = self.buf[i] & 0xFF
                grb[i] = (g<<16) | (r<<8) | b
            self.sm.put(grb, 8)

    def RGBtoHSV(colorInput):
        r = colorInput[0] / 255
        g = colorInput[1] / 255
        b = colorInput[2] / 255
        c_max = max(r, g, b)
        c_min = min(r, g, b)
        delta = c_max - c_min
        if delta == 0:
            h = 0
        elif c_max == r:
            h = (60 * ((g - b) / delta) + 360) % 360
        elif c_max == g:
            h = (60 * ((b - r) / delta) + 120) % 360
        else:
            h = (60 * ((r - g) / delta) + 240) % 360
        s = 0 if c_max == 0 else delta / c_max
        v = c_max
        return (int(round(h, 0)), int(round(s * 100, 0)), int(round(v*100, 0)))

    def HSVtoRGB(colorInput):
        #https://zh.m.wikipedia.org/zh-tw/HSL%E5%92%8CHSV%E8%89%B2%E5%BD%A9%E7%A9%BA%E9%97%B4
        color = [colorInput[0], colorInput[1], colorInput[2]]
        color[1] /= 100
        color[2] /= 100
        hi = color[0] // 60
        f = color[0] / 60 - hi
        p = color[2] * (1 - color[1])
        q = color[2] * (1 - f * color[1])
        t = color[2] * (1 - (1 - f) * color[1])
        if hi == 0:
            return (int(round(color[2] * 255, 0)), int(round(t * 255, 0)), int(round(p * 255, 0)))
        elif hi == 1:
            return (int(round(q * 255, 0)), int(round(color[2] * 255, 0)), int(round(p * 255, 0)))
        elif hi == 2:
            return (int(round(p * 255, 0)), int(round(color[2] * 255, 0)), int(round(t * 255, 0)))
        elif hi == 3:
            return (int(round(p * 255, 0)), int(round(q * 255, 0)), int(round(color[2] * 255, 0)))
        elif hi == 4:
            return (int(round(t * 255, 0)), int(round(p * 255, 0)), int(round(color[2] * 255, 0)))
        elif hi == 5:
            return (int(round(color[2] * 255, 0)), int(round(p * 255, 0)), int(round(q * 255, 0)))

    internalLed = NeoPixel(machine.Pin(2), SUM_OF_INTERNAL_LEDS, 0)
    externalLed = NeoPixel(machine.Pin(3), settings["externalLed"]["sumOfLeds"], 1)
        
    def setLed(ledType, ledcolor, startNum=0, endNum=SUM_OF_INTERNAL_LEDS, scaleWithBrightness=False):
        if ledType == 1:        #0 internal 1 external
            endNum = settings["externalLed"]["sumOfLeds"]
        color = [ledcolor[0], ledcolor[1], ledcolor[2]]
        if scaleWithBrightness:
            if ledType == 0:
                for i in range(3):
                    color[i] = int(color[i]*settings["internalLed"]["brightness"]/100)
            else:
                for i in range(3):
                    color[i] = int(color[i]*settings["externalLed"]["brightness"]/100)
        if ledType == 0:
            for i in range(startNum, endNum, 1):
                internalLed[i] = tuple(color)
            internalLed.write()
        else:
            for i in range(startNum, endNum, 1):
                externalLed[i] = tuple(color)
            externalLed.write()

    setLed(0, (0, 0, 0))
    setLed(1, (0, 0, 0))

    lastLedButtonState, lastLedButtonPressedTime, lastLedButtonLongPressedTime, lastLedButtonReleasedTime, ledButtonShortPressedTimes = 0, time.ticks_ms(), time.ticks_ms(), time.ticks_ms(), 0
    lastInternalLedMode, lastInternalLedColor, lastInternalLedBrightness = 0, (), 0
    lastExternalLedMode, lastExternalLedColor, lastExternalLedBrightness, lastExternalLedSum = 0, (), 0, settings["externalLed"]["sumOfLeds"]
    internalLedMode3TargetLed = ((3, 4), (6, 7), (9, 10), (12, 13), (15, 16), (18, 19), (21, 22), (24, 25))
    internalLedMode2Param = [0, 0]
    internalLedMode3Param = [0, 0]     #八卦方位 上次動作時間
    internalLedMode4Param = [0, 0]    #H座標, 上次動作時間
    internalLedMode5Param = [0, 0]    #第一顆燈之H座標, 上次動作時間
    externalLedMode2Param = [0, 0]
    externalLedMode3Param = [0, 0, True]     #燈編號, 上次動作時間, 順向亮起（某則逆向）
    externalLedMode4Param = [0, 0]    #H座標, 上次動作時間
    externalLedMode5Param = [0, 0]    #第一顆燈之H座標, 上次動作時間

    def setLastLedColor(ledType):
        if ledType == 0:
            nonlocal lastInternalLedColor, lastInternalLedBrightness
            lastInternalLedColor, lastInternalLedBrightness = settings["internalLed"]["color"], settings["internalLed"]["brightness"]
        else:
            nonlocal lastExternalLedColor, lastExternalLedBrightness
            lastExternalLedColor, lastExternalLedBrightness = settings["externalLed"]["color"], settings["externalLed"]["brightness"]

    def isColorChanged(ledType):
        if ledType == 0:
            return True if settings["internalLed"]["color"] != lastInternalLedColor or settings["internalLed"]["brightness"] != lastInternalLedBrightness else False
        else:
            return True if settings["externalLed"]["color"] != lastExternalLedColor or settings["externalLed"]["brightness"] != lastExternalLedBrightness else False

    while True:
        #調整設定
        settingsChanged = False
        #偵測按鈕狀態
        if lastLedButtonState == 0 and ledButton.value() == 1:
            lastLedButtonPressedTime = time.ticks_ms()
            lastLedButtonState = 1
        if lastLedButtonState == 1 and ledButton.value() == 0 and (time.ticks_diff(time.ticks_ms(), lastLedButtonPressedTime) >= SHORT_PRESS_TIME and time.ticks_diff(time.ticks_ms(), lastLedButtonPressedTime) < LONG_PRESS_TIME and time.ticks_diff(time.ticks_ms(), lastLedButtonLongPressedTime) >= LONG_PRESS_TIME):    #短按
            lastLedButtonState = 0
            lastLedButtonReleasedTime = time.ticks_ms()
            ledButtonShortPressedTimes += 1
        if lastLedButtonState == 1 and ledButton.value() == 0 and (time.ticks_diff(time.ticks_ms(), lastLedButtonPressedTime) < SHORT_PRESS_TIME or time.ticks_diff(time.ticks_ms(), lastLedButtonPressedTime) >= LONG_PRESS_TIME or time.ticks_diff(time.ticks_ms(), lastLedButtonLongPressedTime) < LONG_PRESS_TIME):    #無效放開
            lastLedButtonState = 0
            lastLedButtonReleasedTime = time.ticks_ms()
        if ledButton.value() == 0 and time.ticks_diff(time.ticks_ms(), lastLedButtonReleasedTime) >= RELEASE_TIME and ledButtonShortPressedTimes > 0:  #短按結束
            if ledButtonShortPressedTimes == 1 and (settings["internalLed"]["mode"] in (1, 2, 3)):    #短按一下變色
                ledHsvColor = list(RGBtoHSV(settings["internalLed"]["color"]))
                if ledHsvColor[0] == 0 and ledHsvColor[1] == 0:      #白
                    ledHsvColor[1] = 100     #紅
                else:
                    ledHsvColor[0] = ((ledHsvColor[0] // 30 + 1) * 30) % 360
                    ledHsvColor[1] = 100 if ledHsvColor[0] != 0 else 0
                settings["internalLed"]["color"] = HSVtoRGB(ledHsvColor)
            elif ledButtonShortPressedTimes == 2:    #短按兩下調模式
                settings["internalLed"]["mode"] = settings["internalLed"]["mode"] + 1 if settings["internalLed"]["mode"] <= 4 else 0
            ledButtonShortPressedTimes = 0
            settingsChanged = True
        if lastLedButtonState == 1 and time.ticks_diff(time.ticks_ms(), lastLedButtonPressedTime) >= LONG_PRESS_TIME:      #長按調亮度
            lastLedButtonPressedTime, lastLedButtonLongPressedTime = time.ticks_ms(), time.ticks_ms()
            settings["internalLed"]["brightness"] = settings["internalLed"]["brightness"] - 20 if settings["internalLed"]["brightness"] > 20 else 100
            settingsChanged = True
        if settingsChanged:
            with open("./settings.json", "w", encoding="utf8") as f:
                json.dump(settings, f)
        
        #調整內部燈光
        if settings["internalLed"]["mode"] == 0 and lastInternalLedMode != 0:
            lastInternalLedMode = 0
            setLed(0, (0, 0, 0))
        elif settings["internalLed"]["mode"] == 1:
            if lastInternalLedMode != 1:
                lastInternalLedMode = 1
                setLastLedColor(0)
                setLed(0, settings["internalLed"]["color"], scaleWithBrightness=True)
            elif isColorChanged(0):
                setLastLedColor(0)
                setLed(0, settings["internalLed"]["color"], scaleWithBrightness=True)
        elif settings["internalLed"]["mode"] == 2:
            if lastInternalLedMode != 2:
                lastInternalLedMode = 2
                setLastLedColor(0)
                internalLedMode2Param = [time.ticks_ms(), time.ticks_ms()]
                setLed(0, settings["internalLed"]["color"], scaleWithBrightness=True)
            elif isColorChanged(0):
                setLastLedColor(0)
                if time.ticks_diff(time.ticks_ms(), internalLedMode2Param[0]) < settings["internalLed"]["blinkInterval"]:
                    setLed(0, settings["internalLed"]["color"], scaleWithBrightness=True)
            if lastInternalLedMode == 2 and time.ticks_diff(time.ticks_ms(), internalLedMode2Param[0]) >= settings["internalLed"]["blinkInterval"]:
                if time.ticks_diff(time.ticks_ms(), internalLedMode2Param[1]) < settings["internalLed"]["blinkInterval"] * 2:
                    setLed(0, (0, 0, 0))
                else:
                    internalLedMode2Param = [time.ticks_ms(), time.ticks_ms()]
                    setLed(0, settings["internalLed"]["color"], scaleWithBrightness=True)
        elif settings["internalLed"]["mode"] == 3:
            if lastInternalLedMode != 3:
                lastInternalLedMode = 3
                setLastLedColor(0)
                for i in (0, 1, 2):
                    internalLed[i] = (int(settings["internalLed"]["color"][0]*settings["internalLed"]["brightness"]/100*((100-settings["internalLed"]["radarContrast"])/100)), int(settings["internalLed"]["color"][1]*settings["internalLed"]["brightness"]/100*((100-settings["internalLed"]["radarContrast"])/100)), int(settings["internalLed"]["color"][2]*settings["internalLed"]["brightness"]/100*((100-settings["internalLed"]["radarContrast"])/100)))
                for i in (3, 4):
                    internalLed[i] = (int(settings["internalLed"]["color"][0]*settings["internalLed"]["brightness"]/100), int(settings["internalLed"]["color"][1]*settings["internalLed"]["brightness"]/100), int(settings["internalLed"]["color"][2]*settings["internalLed"]["brightness"]/100))
                for i in range(5, SUM_OF_INTERNAL_LEDS, 1):
                    internalLed[i] = (0, 0, 0)
                internalLedMode3Param[0], internalLedMode3Param[1] = 0, time.ticks_ms()
                internalLed.write()
            elif isColorChanged(0):
                setLastLedColor(0)
                for i in (0, 1, 2):
                    internalLed[i] = (int(settings["internalLed"]["color"][0]*settings["internalLed"]["brightness"]/100*((100-settings["internalLed"]["radarContrast"])/100)), int(settings["internalLed"]["color"][1]*settings["internalLed"]["brightness"]/100*((100-settings["internalLed"]["radarContrast"])/100)), int(settings["internalLed"]["color"][2]*settings["internalLed"]["brightness"]/100*((100-settings["internalLed"]["radarContrast"])/100)))             
                for i in internalLedMode3TargetLed[internalLedMode3Param[0]]:
                    internalLed[i] = (int(settings["internalLed"]["color"][0]*settings["internalLed"]["brightness"]/100), int(settings["internalLed"]["color"][1]*settings["internalLed"]["brightness"]/100), int(settings["internalLed"]["color"][2]*settings["internalLed"]["brightness"]/100))
                internalLed.write()
            if lastInternalLedMode == 3 and time.ticks_diff(time.ticks_ms(), internalLedMode3Param[1]) >= settings["internalLed"]["sequentialStepInterval"]:
                if settings["internalLed"]["sequentialDirection"]:
                    internalLedMode3Param[0] += 1
                    if internalLedMode3Param[0] >= 8:
                        internalLedMode3Param[0] = 0
                else:
                    internalLedMode3Param[0] -= 1
                    if internalLedMode3Param[0] < 0:
                        internalLedMode3Param[0] = 7
                for i in (0, 1, 2):
                    internalLed[i] = (int(settings["internalLed"]["color"][0]*settings["internalLed"]["brightness"]/100*((100-settings["internalLed"]["radarContrast"])/100)), int(settings["internalLed"]["color"][1]*settings["internalLed"]["brightness"]/100*((100-settings["internalLed"]["radarContrast"])/100)), int(settings["internalLed"]["color"][2]*settings["internalLed"]["brightness"]/100*((100-settings["internalLed"]["radarContrast"])/100)))
                for i in range(3, SUM_OF_INTERNAL_LEDS, 1):
                    if i in internalLedMode3TargetLed[internalLedMode3Param[0]]:
                        internalLed[i] = (int(settings["internalLed"]["color"][0]*settings["internalLed"]["brightness"]/100), int(settings["internalLed"]["color"][1]*settings["internalLed"]["brightness"]/100), int(settings["internalLed"]["color"][2]*settings["internalLed"]["brightness"]/100))
                    else:
                        internalLed[i] = (0, 0, 0)
                internalLedMode3Param[1] = time.ticks_ms()
                internalLed.write()
        elif settings["internalLed"]["mode"] == 4:
            setLastLedColor(0)
            if lastInternalLedMode != 4:
                lastInternalLedMode = 4
                internalLedMode4Param = [0, time.ticks_ms()]
                setLed(0, HSVtoRGB((internalLedMode4Param[0], 100, settings["internalLed"]["brightness"])))
            elif time.ticks_diff(time.ticks_ms(), internalLedMode4Param[1]) >= settings["internalLed"]["colorCycleTime"] / 360:
                internalLedMode4Param[0] += int(round(time.ticks_diff(time.ticks_ms(), internalLedMode4Param[1]) / (settings["internalLed"]["colorCycleTime"]/360), 0))
                if internalLedMode4Param[0] >= 360:
                    internalLedMode4Param[0] = 0
                internalLedMode4Param[1] = time.ticks_ms()
                setLed(0, HSVtoRGB((internalLedMode4Param[0], 100, settings["internalLed"]["brightness"])))
        elif settings["internalLed"]["mode"] == 5:
            setLastLedColor(0)
            if lastInternalLedMode != 5:
                lastInternalLedMode = 5
                for i in range(SUM_OF_INTERNAL_LEDS):
                    h = internalLedMode5Param[0] + i*settings["internalLed"]["rainbowColorStep"]
                    h = h if h < 360 else h % 360
                    internalLed[i] = HSVtoRGB((h, 100, settings["internalLed"]["brightness"]))
                internalLedMode5Param[0], internalLedMode5Param[1] = 0, time.ticks_ms()
                internalLed.write()
            elif time.ticks_diff(time.ticks_ms(), internalLedMode5Param[1]) >= settings["internalLed"]["colorCycleTime"] / 360:
                internalLedMode5Param[0] += int(round(time.ticks_diff(time.ticks_ms(), internalLedMode5Param[1]) / (settings["internalLed"]["colorCycleTime"]/360), 0))
                if internalLedMode5Param[0] >= 360:
                    internalLedMode5Param[0] = 0
                for i in range(SUM_OF_INTERNAL_LEDS):
                    h = internalLedMode5Param[0] + i*settings["internalLed"]["rainbowColorStep"]
                    h = h if h < 360 else h % 360
                    internalLed[i] = HSVtoRGB((h, 100, settings["internalLed"]["brightness"]))
                internalLedMode5Param[1] = time.ticks_ms()
                internalLed.write()

        #調整外部燈光
        if settings["externalLed"]["sumOfLeds"] != lastExternalLedSum:
            for i in range(lastExternalLedSum):
                externalLed[i] = (0, 0, 0)
            externalLed.write()
            lastExternalLedSum = settings["externalLed"]["sumOfLeds"]
            externalLed = NeoPixel(machine.Pin(3), settings["externalLed"]["sumOfLeds"], 1)
        if settings["externalLed"]["mode"] == 0 and lastExternalLedMode != 0:
            lastExternalLedMode = 0
            setLed(1, (0, 0, 0))
        elif settings["externalLed"]["mode"] == 1:
            if lastExternalLedMode != 1:
                lastExternalLedMode = 1
                setLastLedColor(1)
                setLed(1, settings["externalLed"]["color"], scaleWithBrightness=True)
            elif isColorChanged(1):
                setLastLedColor(1)
                setLed(1, settings["externalLed"]["color"], scaleWithBrightness=True)
        elif settings["externalLed"]["mode"] == 2:
            if lastExternalLedMode != 2:
                lastExternalLedMode = 2
                setLastLedColor(1)
                externalLedMode2Param = [time.ticks_ms(), time.ticks_ms()]
                setLed(1, settings["externalLed"]["color"], scaleWithBrightness=True)
            elif isColorChanged(1):
                setLastLedColor(1)
                if time.ticks_diff(time.ticks_ms(), externalLedMode2Param[0]) < settings["externalLed"]["blinkInterval"]:
                    setLed(0, settings["externalLed"]["color"], scaleWithBrightness=True)
            if lastExternalLedMode == 2 and time.ticks_diff(time.ticks_ms(), externalLedMode2Param[0]) >= settings["externalLed"]["blinkInterval"]:
                if time.ticks_diff(time.ticks_ms(), externalLedMode2Param[1]) < settings["externalLed"]["blinkInterval"] * 2:
                    setLed(1, (0, 0, 0))
                else:
                    externalLedMode2Param = [time.ticks_ms(), time.ticks_ms()]
                    setLed(1, settings["externalLed"]["color"], scaleWithBrightness=True)
        elif settings["externalLed"]["mode"] == 3:
            if lastExternalLedMode != 3:
                lastExternalLedMode = 3
                setLastLedColor(1)
                externalLed[0] = (int(settings["externalLed"]["color"][0]*settings["externalLed"]["brightness"]/100), int(settings["externalLed"]["color"][1]*settings["externalLed"]["brightness"]/100), int(settings["externalLed"]["color"][2]*settings["externalLed"]["brightness"]/100))
                for i in range(1, settings["externalLed"]["sumOfLeds"], 1):
                    externalLed[i] = (0, 0, 0)
                externalLedMode3Param = [0, time.ticks_ms(), True]
                externalLed.write()
            elif isColorChanged(1):
                setLastLedColor(1)
                externalLed[externalLedMode3Param[0]] = (int(settings["externalLed"]["color"][0]*settings["externalLed"]["brightness"]/100), int(settings["externalLed"]["color"][1]*settings["externalLed"]["brightness"]/100), int(settings["externalLed"]["color"][2]*settings["externalLed"]["brightness"]/100))
                externalLed.write()
            if lastExternalLedMode == 3 and time.ticks_diff(time.ticks_ms(), externalLedMode3Param[1]) >= settings["externalLed"]["sequentialStepInterval"]:
                if externalLedMode3Param[2]:
                    externalLedMode3Param[0] += 1
                    if externalLedMode3Param[0] >= settings["externalLed"]["sumOfLeds"]:
                        externalLedMode3Param[0] = settings["externalLed"]["sumOfLeds"] - 2
                        externalLedMode3Param[2] = False
                else:
                    externalLedMode3Param[0] -= 1
                    if externalLedMode3Param[0] < 0:
                        externalLedMode3Param[0] = 1
                        externalLedMode3Param[2] = True
                for i in range(0, settings["externalLed"]["sumOfLeds"], 1):
                    if i == externalLedMode3Param[0]:
                        externalLed[i] = (int(settings["externalLed"]["color"][0]*settings["externalLed"]["brightness"]/100), int(settings["externalLed"]["color"][1]*settings["externalLed"]["brightness"]/100), int(settings["externalLed"]["color"][2]*settings["externalLed"]["brightness"]/100))
                    else:
                        externalLed[i] = (0, 0, 0)
                externalLedMode3Param[1] = time.ticks_ms()
                externalLed.write()
        elif settings["externalLed"]["mode"] == 4:
            setLastLedColor(1)
            if lastExternalLedMode != 4:
                lastExternalLedMode = 4
                externalLedMode4Param = [0, time.ticks_ms()]
                setLed(1, HSVtoRGB((externalLedMode4Param[0], 100, settings["externalLed"]["brightness"])))
            elif time.ticks_diff(time.ticks_ms(), externalLedMode4Param[1]) >= settings["externalLed"]["colorCycleTime"] / 360:
                externalLedMode4Param[0] += int(round(time.ticks_diff(time.ticks_ms(), externalLedMode4Param[1]) / (settings["externalLed"]["colorCycleTime"]/360), 0))
                if externalLedMode4Param[0] >= 360:
                    externalLedMode4Param[0] = 0
                externalLedMode4Param[1] = time.ticks_ms()
                setLed(1, HSVtoRGB((externalLedMode4Param[0], 100, settings["externalLed"]["brightness"])))
        elif settings["externalLed"]["mode"] == 5:
            setLastLedColor(1)
            if lastExternalLedMode != 5:
                lastExternalLedMode = 5
                for i in range(settings["externalLed"]["sumOfLeds"]):
                    h = externalLedMode5Param[0] + i*settings["externalLed"]["rainbowColorStep"]
                    h = h if h < 360 else h % 360
                    externalLed[i] = HSVtoRGB((h, 100, settings["externalLed"]["brightness"]))
                externalLedMode5Param[0], internalLedMode5Param[1] = 0, time.ticks_ms()
                externalLed.write()
            elif time.ticks_diff(time.ticks_ms(), externalLedMode5Param[1]) >= settings["externalLed"]["colorCycleTime"] / 360:                
                externalLedMode5Param[0] += int(round(time.ticks_diff(time.ticks_ms(), externalLedMode5Param[1]) / (settings["externalLed"]["colorCycleTime"]/360), 0))
                if externalLedMode5Param[0] >= 360:
                    externalLedMode5Param[0] = 0
                for i in range(settings["externalLed"]["sumOfLeds"]):
                    h = externalLedMode5Param[0] + i*settings["externalLed"]["rainbowColorStep"]
                    h = h if h < 360 else h % 360
                    externalLed[i] = HSVtoRGB((h, 100, settings["externalLed"]["brightness"]))
                externalLedMode5Param[1] = time.ticks_ms()
                externalLed.write()

async def main():

    bigFonts = ((0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x80, 0xC0, 0xE0, 0xE0, 0xE0, 0xE0, 0xE0, 0xC0, 0xC0, 0x80, 0x00,
    0x00, 0x00, 0x00, 0x00, 0xFC, 0xFF, 0xFF, 0x07, 0x01, 0x00, 0x00, 0x00, 0x00, 0x01, 0x0F, 0xFF,
    0xFE, 0xF8, 0x00, 0x00, 0x00, 0x3F, 0xFF, 0xFF, 0xE0, 0x80, 0x00, 0x00, 0x00, 0x00, 0x80, 0xF0,
    0xFF, 0x7F, 0x0F, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x03, 0x07, 0x07, 0x07, 0x07, 0x07, 0x03,
    0x03, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00), 
    (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x80, 0xC0, 0xC0, 0xC0, 0xE0, 0xE0, 0xE0, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x01, 0x01, 0x01, 0xFF, 0xFF, 0xFF, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xFF, 0xFF, 0xFF, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x07, 0x07, 0x07, 0x07, 0x07, 0x07, 0x07, 0x07, 0x07,
    0x07, 0x07, 0x07, 0x07, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00), 
    (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x80, 0xC0, 0xC0, 0xE0, 0xE0, 0xE0, 0xE0, 0xE0, 0xC0, 0xC0, 0x80, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x01, 0x03, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00, 0x01, 0xC3, 0xFF, 0xFF,
    0x3E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x80, 0xC0, 0xE0, 0xF0, 0x78, 0x3E, 0x1F, 0x0F, 0x03,
    0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x06, 0x07, 0x07, 0x07, 0x07, 0x07, 0x07, 0x07, 0x07, 0x07,
    0x07, 0x07, 0x07, 0x07, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00), 
    (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x80, 0xC0, 0xC0, 0xE0, 0xE0, 0xE0, 0xE0, 0xE0, 0xC0, 0xC0, 0x80, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x01, 0x01, 0x80, 0x80, 0xC0, 0xC0, 0xE0, 0xF3, 0x7F, 0x3F,
    0x1F, 0x00, 0x00, 0x00, 0x00, 0x80, 0xC0, 0x80, 0x00, 0x01, 0x01, 0x01, 0x01, 0x03, 0x83, 0xEF,
    0xFE, 0xFE, 0x78, 0x00, 0x00, 0x00, 0x01, 0x03, 0x03, 0x03, 0x07, 0x07, 0x07, 0x07, 0x07, 0x03,
    0x03, 0x03, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00), 
    (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xC0, 0xE0, 0xE0, 0xE0, 0xE0, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xC0, 0xF0, 0xF8, 0x3E, 0x1F, 0x07, 0x01, 0xFF, 0xFF, 0xFF,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x1E, 0x1F, 0x1F, 0x1D, 0x1C, 0x1C, 0x1C, 0x1C, 0x1C, 0xFF, 0xFF,
    0xFF, 0x1C, 0x1C, 0x1C, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x07,
    0x07, 0x07, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00), 
    (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0xE0, 0xE0, 0xE0, 0xE0, 0xE0, 0xE0, 0xE0, 0xE0, 0xE0, 0xE0, 0xE0,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x78, 0xFF, 0xFF, 0x63, 0x60, 0x60, 0x60, 0x60, 0xE0, 0xE0, 0xC0,
    0x80, 0x00, 0x00, 0x00, 0x00, 0x80, 0xC0, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x80, 0xF7,
    0xFF, 0xFF, 0x3E, 0x00, 0x00, 0x00, 0x01, 0x03, 0x03, 0x07, 0x07, 0x07, 0x07, 0x07, 0x07, 0x03,
    0x03, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00), 
    (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x80, 0xC0, 0xC0, 0xE0, 0xE0, 0xE0, 0xE0, 0xE0, 0xC0, 0xC0,
    0x00, 0x00, 0x00, 0x00, 0xF0, 0xFE, 0xFF, 0x8F, 0xC3, 0xC1, 0xE0, 0x60, 0xE0, 0xE0, 0xC0, 0xC1,
    0x81, 0x00, 0x00, 0x00, 0x00, 0x0F, 0x7F, 0xFF, 0xE1, 0x81, 0x00, 0x00, 0x00, 0x00, 0x00, 0x81,
    0xFF, 0xFF, 0x7E, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x03, 0x03, 0x07, 0x07, 0x06, 0x07, 0x07,
    0x03, 0x03, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00), 
    (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0xE0, 0xE0, 0xE0, 0xE0, 0xE0, 0xE0, 0xE0, 0xE0, 0xE0, 0xE0, 0xE0, 0xE0, 0xE0,
    0xE0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x80, 0xE0, 0xF8, 0xFE, 0x1F, 0x07,
    0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xF8, 0xFF, 0xFF, 0x0F, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x07, 0x07, 0x07, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00), 
    (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x80, 0xC0, 0xC0, 0xE0, 0x60, 0xE0, 0xE0, 0xC0, 0xC0, 0x80, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x1F, 0x3F, 0x7F, 0xF1, 0xE0, 0xC0, 0x80, 0xC0, 0xE1, 0xFF, 0x3F,
    0x1E, 0x00, 0x00, 0x00, 0x00, 0x78, 0xFE, 0xFE, 0x87, 0x01, 0x01, 0x01, 0x01, 0x03, 0x03, 0x87,
    0xFF, 0xFE, 0xF8, 0x00, 0x00, 0x00, 0x00, 0x01, 0x03, 0x03, 0x07, 0x07, 0x06, 0x06, 0x07, 0x07,
    0x03, 0x03, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00), 
    (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x80, 0xC0, 0xC0, 0xE0, 0xE0, 0xE0, 0xE0, 0xE0, 0xC0, 0xC0, 0x80, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x7E, 0xFF, 0xFF, 0xC1, 0x80, 0x00, 0x00, 0x00, 0x00, 0x81, 0xC7, 0xFF,
    0xFE, 0xF8, 0x00, 0x00, 0x00, 0x00, 0x81, 0x81, 0x03, 0x03, 0x03, 0x03, 0x03, 0x83, 0xC1, 0xF0,
    0xFF, 0x7F, 0x0F, 0x00, 0x00, 0x00, 0x00, 0x03, 0x03, 0x07, 0x07, 0x07, 0x07, 0x07, 0x03, 0x03,
    0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00), 
    (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x80, 0xC0, 0xC0, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x03, 0x07,
    0x07, 0x03, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00), 
    (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x60, 0xE0, 0xE0, 0xE0,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xE0, 0xE0, 0xE0, 0xC0, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0xE0, 0xE0, 0xE0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x0F, 0xFF, 0xFF, 0xFC, 0x00,
    0x00, 0x00, 0x00, 0xE0, 0xFE, 0x7F, 0x03, 0x1F, 0xFF, 0xFC, 0xC0, 0x00, 0x00, 0x00, 0xC0, 0xFE,
    0xFF, 0x7F, 0x03, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x3F, 0xFF, 0xFF, 0xC0, 0xE0,
    0xFE, 0xFF, 0x0F, 0x00, 0x00, 0x00, 0x01, 0x1F, 0xFF, 0xFC, 0x80, 0xF0, 0xFF, 0xFF, 0x0F, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x03, 0x07, 0x07, 0x07, 0x07, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x07, 0x07, 0x07, 0x07, 0x01, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00))        #0123456789.W

    def url_decode(url):
        res = []
        i = 0
        length = len(url)
        while i < length:
            if url[i] == "+":
                res.append(" ")
                i += 1
            elif url[i] == "%" and i + 2 < length:
                hexValue = url[i+1:i+3]
                res.append(chr(int(hexValue, 16)))
                i += 3
            else:
                res.append(url[i])
                i += 1
        return "".join(res)

    def parse_query(request):       #by GPT-4o mini
        try:
            # 從第一行擷取 GET 請求
            line = url_decode(request.decode("utf8"))
            if line.lower().startswith("get"):
                line.split("\r\n")[0]  # e.g. GET /?led=on&color=red HTTP/1.1
                path = line.split(" ")[1]        # /?led=on&color=red
                if "?" not in path:
                    return {}
                query = path.split("?")[1]       # led=on&color=red
                params = {}
                for pair in query.split("&"):
                    if "=" in pair:
                        key, value = pair.split("=")
                        params[key] = value
                return params
            elif line.lower().startswith("post"):
                body = line.split("\r\n\r\n", 1)[1]
                params = {}
                for pair in body.split("&"):
                    if "=" in pair:
                        key, value = pair.split("=", 1)
                        params[key] = value
                return params
        except:
            return {}

    def web_page():
        internalLedColorHex = "#{:02x}{:02x}{:02x}".format(settings["internalLed"]["color"][0], settings["internalLed"]["color"][1], settings["internalLed"]["color"][2])
        externalLedColorHex = "#{:02x}{:02x}{:02x}".format(settings["externalLed"]["color"][0], settings["externalLed"]["color"][1], settings["externalLed"]["color"][2])
        
        html = """<html><head><meta charset="UTF-8"><title>&#20843;&#21350;&#27969;&#20809;&#29200;&#9734;</title><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="icon" href="data:,">
        <style>
        html{font-family: Helvetica; display:inline-block; margin: 0px auto; text-align: center;}
        body{background-image: linear-gradient(rgba(255, 255, 255, 0.5), rgba(255, 255, 255, 0.5)), url(\""""+settings["backgroundImageUrl"]+"""\"); background-size: cover; background-repeat: no-repeat; background-position: center;}
        h1{color: #000000; padding: 2vh;}
        label{font-size: 14px; font-family: Arial, sans-serif;}
        p{font-size: 1.5rem;}        
        .form_container{justify-content: center; margin: 20px auto;}
        .form_box{max-width: 400px; padding: 15px; margin: 0 auto; border: 1px solid #ccc; border-radius: 8px; background-color: rgba(255, 255, 255, 0.2); backdrop-filter: blur(4px); box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);}
        .button{display: inline-block; background-color: #6C757D; border: none; border-radius: 32px; color: white; padding: 12px 32px; text-decoration: none; font-size: 14px; margin: 16px; cursor: pointer;}
        .button2{background-color: #007BFF;}
        .hidden {display: none;}
        </style></head><body>
        <div class="wrapper">
        <h1>&#20843;&#21350;&#27969;&#20809;&#29200;&#9734;</h1>

        <div class="led_settings_type"><p>
            <h3>LED settings</h3>
            <label><input type="radio" name="led_type" value="internal" checked>internal</label>
            <label><input type="radio" name="led_type" value="external">external</label>
        </p></div>

        <div class="OOF_form_container">
        <form id="internal_led_form" class="form_box" action="/" method="GET">        
        <p>
            <label for="internal_led_mode">Light Effect</label>
            <select id="internal_led_mode" name="internalLedMode">
                <option value="0" """+("selected" if settings["internalLed"]["mode"] == 0 else "")+""">Disabled</option>
                <option value="1" """+("selected" if settings["internalLed"]["mode"] == 1 else "")+""">Static</option>
                <option value="2" """+("selected" if settings["internalLed"]["mode"] == 2 else "")+""">Blink</option>
                <option value="3" """+("selected" if settings["internalLed"]["mode"] == 3 else "")+""">Radar</option>
                <option value="4" """+("selected" if settings["internalLed"]["mode"] == 4 else "")+""">Color Cycle</option>
                <option value="5" """+("selected" if settings["internalLed"]["mode"] == 5 else "")+""">Rainbow</option>
            </select>
        </p>
        <p>
            <label for="internal_led_color_picker">Color</label>
            <input id="internal_led_color_picker" type="color" name="internalLedColor" value=\""""+internalLedColorHex+"""\">
        </p>
        <p>
            <label for="internal_led_brightness_range">Brightness</label>
            <input id="internal_led_brightness_range" type="range" name="internalLedBrightness" min="0" max="100" value=\""""+str(settings["internalLed"]["brightness"])+"""\">
        </p>
        <p>
            <label for="internal_led_blink_time">Blink Interval</label>
            <input id="internal_led_blink_time" type="number" name="internalLedBlinkInterval" min="10" max="100000" value=\""""+str(settings["internalLed"]["blinkInterval"])+"""\">
            
        </p>
        <p>
            <label for="internal_led_sequential_time">Sequential Step Interval</label>
            <input id="internal_led_sequential_time" type="number" name="internalLedSequentialStepInterval" min="10" max="100000" value=\""""+str(settings["internalLed"]["sequentialStepInterval"])+"""\">
        </p>
        <p>
            <label>Radar Direction</label>
            <label><input id="internal_led_sequential_direction" type="radio" name="internalLedSequentialDirection" value="true" """+("checked" if settings["internalLed"]["sequentialDirection"] else "")+""">&#8635;</label>
            <label><input id="internal_led_sequential_direction" type="radio" name="internalLedSequentialDirection" value="false" """+("" if settings["internalLed"]["sequentialDirection"] else "checked")+""">&#8634;</label>
        </p>
        <p>
            <label for="internal_led_radar_contrast">Radar Contrast</label>
            <input id="internal_led_radar_contrast" type="range" name="internalLedRadarContrast" min="0" max="100" value=\""""+str(settings["internalLed"]["radarContrast"])+"""\">
        </p>
        <p>
            <label for="internal_led_color_cycle_time">Color Cycle Time</label>
            <input id="internal_led_color_cycle_time" type="number" name="internalLedColorCycleTime" min="100" max="100000" value=\""""+str(settings["internalLed"]["colorCycleTime"])+"""\">
        </p>
        <p>
            <label for="internal_led_rainbow_color_step">Rainbow Color Step</label>
            <input id="internal_led_rainbow_color_step" type="number" name="internalLedRainbowColorStep" min="1" max="359" value=\""""+str(settings["internalLed"]["rainbowColorStep"])+"""\">
        </p>
        <p>
            <button class="button" name="internalLedRestoreDefault" value="true">Default</button>
            <button class="button button2" type="submit">OK</button>
        </p>
        </form>

        <form id="external_led_form" class="form_box hidden" action="/" method="GET">        
        <p>
            <label for="external_led_mode">Light Effect</label>
            <select id="external_led_mode" name="externalLedMode">
                <option value="0" """+("selected" if settings["externalLed"]["mode"] == 0 else "")+""">Disabled</option>
                <option value="1" """+("selected" if settings["externalLed"]["mode"] == 1 else "")+""">Static</option>
                <option value="2" """+("selected" if settings["externalLed"]["mode"] == 2 else "")+""">Blink</option>
                <option value="3" """+("selected" if settings["externalLed"]["mode"] == 3 else "")+""">Sequential</option>
                <option value="4" """+("selected" if settings["externalLed"]["mode"] == 4 else "")+""">Color Cycle</option>
                <option value="5" """+("selected" if settings["externalLed"]["mode"] == 5 else "")+""">Rainbow</option>
            </select>
        </p>
        <p>
            <label for="external_led_color_picker">Color</label>
            <input id="external_led_color_picker" type="color" name="externalLedColor" value=\""""+externalLedColorHex+"""\">
        </p>
        <p>
            <label for="external_led_brightness_range">Brightness</label>
            <input id="external_led_brightness_range" type="range" name="externalLedBrightness" min="0" max="100" value=\""""+str(settings["externalLed"]["brightness"])+"""\">
        </p>
        <p>
            <label for="external_led_blink_time">Blink Interval</label>
            <input id="external_led_blink_time" type="number" name="externalLedBlinkInterval" min="10" max="100000" value=\""""+str(settings["externalLed"]["blinkInterval"])+"""\">
        </p>
        <p>
            <label for="external_led_sequential_time">Sequential Step Interval</label>
            <input id="external_led_sequential_time" type="number" name="externalLedSequentialStepInterval" min="10" max="100000" value=\""""+str(settings["externalLed"]["sequentialStepInterval"])+"""\">
        </p>
        <p>
            <label for="external_led_color_cycle_time">Color Cycle Time</label>
            <input id="external_led_color_cycle_time" type="number" name="externalLedColorCycleTime" min="100" max="100000" value=\""""+str(settings["externalLed"]["colorCycleTime"])+"""\">
        </p>
        <p>
            <label for="external_led_rainbow_color_step">Rainbow Color Step</label>
            <input id="external_led_rainbow_color_step" type="number" name="externalLedRainbowColorStep" min="1" max="359" value=\""""+str(settings["externalLed"]["rainbowColorStep"])+"""\">
        </p>
         <p>
            <label for="external_led_num_of_leds">Number of LEDs</label>
            <input id="external_led_number_of_leds" type="number" name="externalLedSumOfLeds" min="1" max="120" value=\""""+str(settings["externalLed"]["sumOfLeds"])+"""\">
        </p>
        <p>
            <button class="button" name="externalLedRestoreDefault" value="true">Default</button>
            <button class="button button2" type="submit">OK</button>
        </p>
        </form>
        </div>       

        <p> <h3>System Settings</h3> </p>
        <form class="form_box" action="/" method="POST">
        <p>
            <label for="background_image_url">Background Image URL</label>
            <input id="background_image_url" type="text" name="backgroundImageUrl" value=\""""+str(settings["backgroundImageUrl"])+"""\">
        </p>
        <div class="radio_group">
            <label><input type="radio" name="wifiMode" value="0"
                """ + ("checked" if settings["wifi"]["mode"]==0 else "") + """>AP</label>
            <label><input type="radio" name="wifiMode" value="1"
                """ + ("checked" if settings["wifi"]["mode"]==1 else "") + """>STA</label>
        </div>

        <p>
            <label for="ssid_text">SSID</label>
            <input id="ssid_text" type="text" name="ssid" value=\""""+str(settings["wifi"]["ssid"])+"""\">
        </p>
        <p>
            <label for="password_text">password</label>
            <input id="password_text" type="password" name="password" value="">
        </p>

        <p>
            <button class="button" name="restoreDefault" value="true">Default</button>
            <button class="button button2" type="submit">OK</button>
        </p>
        </form>
        <script>
            const ledType = document.querySelectorAll('input[name="led_type"]');
            const internalLedForm = document.getElementById('internal_led_form');
            const externalLedForm = document.getElementById('external_led_form');
            ledType.forEach(radio => {
                radio.addEventListener('change', e => {
                    const value = e.target.value;
                    if (value === 'internal') {
                        internalLedForm.classList.remove('hidden');
                        externalLedForm.classList.add('hidden');
                    } else if (value === 'external') {
                        internalLedForm.classList.add('hidden');
                        externalLedForm.classList.remove('hidden');
                    }
                });
            });
        </script>
        </div>
        </body></html>"""
        return html

    async def handle_client(reader, writer):
        request = await reader.read(1024)
        if request.decode("utf8").lower().startswith("post"):       #接收POST回應body
            for i in request.decode("utf8").split("\r\n"):
                if i.lower().startswith("content-length: ") and request.decode("utf8").partition("\r\n\r\n")[2] == "":
                    request += await reader.read(1024)
                    break
        params = parse_query(request)
        if not params:
            params = {}     #避免非同步執行AttributeError: 'NoneType' object has no attribute 'get'
        settingsChanged = False
        reboot = False
        #系統設定
        if params.get("wifiMode") and params.get("wifiMode") in ("0", "1"):
            if settings["wifi"]["mode"] != int(params["wifiMode"]):
                settings["wifi"]["mode"] = int(params["wifiMode"])
                settingsChanged, reboot = True, True
        if params.get("ssid"):      #None或""不處理
            if settings["wifi"]["ssid"] != params["ssid"]:
                settings["wifi"]["ssid"] = params["ssid"]
                settingsChanged, reboot = True, True
        if params.get("password"):
            if settings["wifi"]["password"] != params["password"]:
                settings["wifi"]["password"] = params["password"]
                settingsChanged, reboot = True, True
        if params.get("backgroundImageUrl"):
            if settings["backgroundImageUrl"] != params["backgroundImageUrl"]:
                settings["backgroundImageUrl"] = params["backgroundImageUrl"]
                settingsChanged = True
        if params.get("restoreDefault") == "true":
            restore_default_settings(1)
            reboot = True
        #內部LED
            settingsChanged = True
        if params.get("internalLedMode") and params.get("internalLedMode") in ("0", "1", "2", "3", "4", "5"):
            settings["internalLed"]["mode"] = int(params["internalLedMode"])
            settingsChanged = True
        if params.get("internalLedColor"):
            try:
                color = params["internalLedColor"][1:7]
                color = tuple(int(color[i:i+2], 16) for i in (0, 2, 4))
            except:
                pass
            else:
                settings["internalLed"]["color"] = color 
                settingsChanged = True
        if params.get("internalLedBrightness"):
            try:
                brightness = settings["internalLed"]["brightness"]
                if int(params["internalLedBrightness"]) >= 0 and int(params["internalLedBrightness"]) <= 100:
                    brightness = int(params["internalLedBrightness"])
            except:
                pass
            else:
                settings["internalLed"]["brightness"] = brightness
                settingsChanged = True
        if params.get("internalLedBlinkInterval"):
            try:
                blinkInterval = settings["internalLed"]["blinkInterval"]
                if int(params["internalLedBlinkInterval"]) >= 10 and int(params["internalLedBlinkInterval"]) <= 100000:
                    blinkInterval = int(params["internalLedBlinkInterval"])
            except:
                pass
            else:
                settings["internalLed"]["blinkInterval"] = blinkInterval
                settingsChanged = True
        if params.get("internalLedSequentialStepInterval"):
            try:
                sequentialStepInterval = settings["internalLed"]["sequentialStepInterval"]
                if int(params["internalLedSequentialStepInterval"]) >= 10 and int(params["internalLedSequentialStepInterval"]) <= 100000:
                    sequentialStepInterval = int(params["internalLedSequentialStepInterval"])
            except:
                pass
            else:
                settings["internalLed"]["sequentialStepInterval"] = sequentialStepInterval
                settingsChanged = True
        if params.get("internalLedSequentialDirection") == "true":
            settings["internalLed"]["sequentialDirection"] = True
            settingsChanged = True
        elif params.get("internalLedSequentialDirection") == "false":
            settings["internalLed"]["sequentialDirection"] = False
            settingsChanged = True
        if params.get("internalLedRadarContrast"):
            try:
                contrast = settings["internalLed"]["radarContrast"]
                if int(params["internalLedRadarContrast"]) >= 0 and int(params["internalLedRadarContrast"]) <= 100:
                    contrast = int(params["internalLedRadarContrast"])
            except:
                pass
            else:
                settings["internalLed"]["radarContrast"] = contrast
                settingsChanged = True
        if params.get("internalLedCycleTime"):
            try:
                colorCycleTime = settings["internalLed"]["colorCycleTime"]
                if int(params["internalLedColorCycleTime"]) >= 100 and int(params["internalLedColorCycleTime"]) <= 100000:
                    colorCycleTime = int(params["internalLedColorCycleTime"])
            except:
                pass
            else:
                settings["internalLed"]["colorCycleTime"] = colorCycleTime
                settingsChanged = True
        if params.get("internalLedRainbowColorStep"):
            try:
                rainbowColorStep = settings["internalLed"]["rainbowColorStep"]
                if int(params["internalLedRainbowColorStep"]) >= 1 and int(params["internalLedRainbowColorStep"]) <= 359:
                    rainbowColorStep = int(params["internalLedRainbowColorStep"])
            except:
                pass
            else:
                settings["internalLed"]["rainbowColorStep"] = rainbowColorStep
                settingsChanged = True
        if params.get("internalLedRestoreDefault") == "true":
            restore_default_settings(2)
        #外部LED
            settingsChanged = True
        if params.get("externalLedMode") and params.get("externalLedMode") in ("0", "1", "2", "3", "4", "5"):
            settings["externalLed"]["mode"] = int(params["externalLedMode"])
            settingsChanged = True
        if params.get("externalLedColor"):
            try:
                color = params["externalLedColor"][1:7]
                color = tuple(int(color[i:i+2], 16) for i in (0, 2, 4))
            except:
                pass
            else:
                settings["externalLed"]["color"] = color
                settingsChanged = True
        if params.get("externalLedBrightness"):
            try:
                brightness = settings["externalLed"]["brightness"]
                if int(params["externalLedBrightness"]) >= 0 and int(params["externalLedBrightness"]) <= 100:
                    brightness = int(params["externalLedBrightness"])
            except:
                pass
            else:
                settings["externalLed"]["brightness"] = brightness
                settingsChanged = True
        if params.get("externalLedBlinkInterval"):
            try:
                blinkInterval = settings["externalLed"]["blinkInterval"]
                if int(params["externalLedBlinkInterval"]) >= 10 and int(params["externalLedBlinkInterval"]) <= 100000:
                    blinkInterval = int(params["externalLedBlinkInterval"])
            except:
                pass
            else:
                settings["externalLed"]["blinkInterval"] = blinkInterval
                settingsChanged = True
        if params.get("externalLedCycleTime"):
            try:
                colorCycleTime = settings["externalLed"]["colorCycleTime"]
                if int(params["externalLedColorCycleTime"]) >= 100 and int(params["externalLedColorCycleTime"]) <= 100000:
                    colorCycleTime = int(params["externalLedColorCycleTime"])
            except:
                pass
            else:
                settings["externalLed"]["colorCycleTime"] = colorCycleTime
                settingsChanged = True
        if params.get("externalLedSequentialStepInterval"):
            try:
                sequentialStepInterval = settings["externalLed"]["sequentialStepInterval"]
                if int(params["externalLedSequentialStepInterval"]) >= 10 and int(params["externalLedSequentialStepInterval"]) <= 100000:
                    sequentialStepInterval = int(params["externalLedSequentialStepInterval"])
            except:
                pass
            else:
                settings["externalLed"]["sequentialStepInterval"] = sequentialStepInterval
                settingsChanged = True
        if params.get("externalLedRainbowColorStep"):
            try:
                rainbowColorStep = settings["externalLed"]["rainbowColorStep"]
                if int(params["externalLedRainbowColorStep"]) >= 1 and int(params["externalLedRainbowColorStep"]) <= 359:
                    rainbowColorStep = int(params["externalLedRainbowColorStep"])
            except:
                pass
            else:
                settings["externalLed"]["rainbowColorStep"] = rainbowColorStep
                settingsChanged = True
        if params.get("externalLedSumOfLeds"):
            try:
                numOfLeds = settings["externalLed"]["sumOfLeds"]
                if int(params["externalLedSumOfLeds"]) >= 1 and int(params["externalLedSumOfLeds"]) <= 120:
                    numOfLeds = int(params["externalLedSumOfLeds"])
            except:
                pass
            else:
                settings["externalLed"]["sumOfLeds"] = numOfLeds
                settingsChanged = True
        if params.get("externalLedRestoreDefault") == "true":
            restore_default_settings(3)
        
        await writer.awrite("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n"+web_page())
        await writer.aclose()

        if settingsChanged:
            with open("./settings.json", "w", encoding="utf8") as f:
                json.dump(settings, f)
        if reboot:
            pass        #手動斷電重啟避免無法連線，不能machine.reset()

    _thread.start_new_thread(led_process, ())

    vBatAdc = machine.ADC(2)
    internalI2c = machine.I2C(0, freq=400000)
    externalI2c = machine.I2C(1, scl=machine.Pin(15), sda=machine.Pin(14), freq=400000)
    powerIc = ina226.INA226(internalI2c)
    powerIc.set_calibration_custom(4750)        #手上有的機器測出來4700~5000 INA226才準確
    powerIc._power_lsb = 0.0026947      #25*(上面數字/(2**15))
    if ENABLE_INA226_OCP:
        powerIc._write_register(0x07, 0xC180)       #typeC 輸入 4A OCP
        powerIc._write_register(0x06, 0x4001)       #輸入OCP鎖定，需重新開機解除
    else:
        powerIc._write_register(0x06, 0x0000)
    screen = None
    if 0x3C in externalI2c.scan():
    #    import ssd1306, badapple       中途import會造成編譯出來的韌體有各種毛病
        screen = ssd1306.SSD1306_I2C(128, 64, externalI2c)

    if settings["wifi"]["mode"]:
        wifi = network.WLAN(network.AP_IF)
        wifi.active(False)
        wifi = network.WLAN(network.STA_IF)
        wifi.active(True)
        wifi.connect(settings["wifi"]["ssid"], settings["wifi"]["password"])
        if screen:
            #import ntptime
            ntptime.host = 'tw.pool.ntp.org'
    else:
        wifi = network.WLAN(network.STA_IF)
        wifi.active(False)
        wifi = network.WLAN(network.AP_IF)
        wifi.config(ssid=settings["wifi"]["ssid"], key=settings["wifi"]["password"])
        wifi.active(True)
    MACAddress = (ubinascii.hexlify(network.WLAN().config("mac"), ":").decode()).upper()
    server = await asyncio.start_server(handle_client, "0.0.0.0", 80, backlog=2)

    gc.collect()

    if screen:
        lastScreenButtonState, lastScreenButtonPressedTime, lastScreenButtonLongPressedTime = 0, time.ticks_ms(), time.ticks_ms()
        screenDisplayMode = 0   #0普通 1僅功耗 2badapple 3機器訊息
        lastScreenDisplayMode = 0
        screenDisplay = True
        screenLastRefreshTime = time.ticks_ms()
        badAppleAnimation = badapple.BadApple()
        animationRefreshInterval = 1000 / badAppleAnimation.framesPerSecond
        animationStartTime = time.ticks_ms()
        animationLastRefreshTime = time.ticks_ms()
        lastLoadPowerIcTime = time.ticks_ms()
        startTime = time.ticks_ms()
        voltage, current, currentDirection, power, mWh, vBat = 0, 0, True, 0, 0, 0
        lastNtpSyncTime = 0

        while True:
            if lastScreenButtonState == 0 and screenButton.value() == 1:
                lastScreenButtonPressedTime = time.ticks_ms()
                lastScreenButtonState = 1
            if lastScreenButtonState == 1 and time.ticks_diff(time.ticks_ms(), lastScreenButtonPressedTime) >= LONG_PRESS_TIME:      #長按開關螢幕
                lastScreenButtonPressedTime, lastScreenButtonLongPressedTime = time.ticks_ms(), time.ticks_ms()
                screenDisplay = not screenDisplay
            if lastScreenButtonState == 1 and screenButton.value() == 0 and (time.ticks_diff(time.ticks_ms(), lastScreenButtonPressedTime) >= SHORT_PRESS_TIME and time.ticks_diff(time.ticks_ms(), lastScreenButtonPressedTime) < LONG_PRESS_TIME and time.ticks_diff(time.ticks_ms(), lastScreenButtonLongPressedTime) >= LONG_PRESS_TIME):    #短按
                lastScreenButtonState = 0
                screenDisplayMode += 1
                if screenDisplayMode > 3:
                    screenDisplayMode = 0
            if lastScreenButtonState == 1 and screenButton.value() == 0 and (time.ticks_diff(time.ticks_ms(), lastScreenButtonPressedTime) < SHORT_PRESS_TIME or time.ticks_diff(time.ticks_ms(), lastScreenButtonPressedTime) >= LONG_PRESS_TIME or time.ticks_diff(time.ticks_ms(), lastScreenButtonLongPressedTime) < LONG_PRESS_TIME):    #無效放開
                lastScreenButtonState = 0

            if wifi.isconnected() and ((time.ticks_diff(time.ticks_ms(), lastNtpSyncTime) / 3600000 >= NTP_SYNC_INTERVAL_HR) or not lastNtpSyncTime):
                try:
                    ntptime.settime()
                except:
                    lastNtpSyncTime = 0
                else:
                    timeNow = time.localtime()
                    machine.RTC().datetime((timeNow[0], timeNow[1], timeNow[2], timeNow[6] + 1, timeNow[3] + 8, timeNow[4], timeNow[5], timeNow[7]))
                    lastNtpSyncTime = time.ticks_ms()

            if time.ticks_diff(time.ticks_ms(), lastLoadPowerIcTime) >= LOAD_INA226_INTERVAL:
                lastLoadPowerIcTime = time.ticks_ms()
                current = powerIc.current
                if abs(current) <= 0.01:
                    current = 0
                currentDirection = True if current >= 0 else False
                if current > 0:
                    current = abs(current) * INA226_POSITIVE_CURRENT_COEFFICIENT
                else:
                    current = abs(current) * INA226_NEGATIVE_CURRENT_COEFFICIENT
                voltage = powerIc.bus_voltage
                power = voltage * current
                mWh += power * (LOAD_INA226_INTERVAL / 1000) * 1000 / 3600
                mWh = mWh if mWh < 99999 else 99999

            if screenDisplayMode == 2 and time.ticks_diff(time.ticks_ms(), animationLastRefreshTime) >= animationRefreshInterval:
                if lastScreenDisplayMode != 2:
                    animationStartTime = time.ticks_ms()
                animationLastRefreshTime = time.ticks_ms()
                lastScreenDisplayMode = 2
                frameNum = int(time.ticks_diff(time.ticks_ms(), animationStartTime) // animationRefreshInterval)
                if frameNum >= badAppleAnimation.frameAmount:
                    frameNum = 0
                    animationStartTime = time.ticks_ms()
                screen.buffer = badAppleAnimation.get_frame(frameNum)
                screen.show()
                if frameNum % 5 == 0:
                    gc.collect()

            if time.ticks_diff(time.ticks_ms(), screenLastRefreshTime) >= SCREEN_REFRESH_INTERVAL and screenDisplayMode != 2:
                screenLastRefreshTime = time.ticks_ms()
                if lastScreenDisplayMode == 2:      #避免播放動畫後無法顯示
                    screen = ssd1306.SSD1306_I2C(128, 64, externalI2c)
                screen.fill(0)
                if screenDisplayMode == 0:
                    lastScreenDisplayMode = 0
                    if screenDisplay:
                        if not lastNtpSyncTime:
                            sec = (time.ticks_diff(time.ticks_ms(), startTime)) // 1000
                        if currentDirection:
                            screen.text("USB-C  OUT", 24, 0)
                        else:
                            screen.text("USB-C   IN", 24, 0)
                        screen.text("{:>5.3f}V    {:>5.3f}A".format(round(voltage, 3), round(current, 3)), 0, 16)
                        screen.text("{:>06.3f}W {:>5d}mWh".format(round(power, 3), int(round(mWh, 0))), 0, 32)
                        if lastNtpSyncTime:
                            screen.text('{:02d}/{:02d}   {:02d}:{:02d}:{:02d}'.format(time.localtime()[1], time.localtime()[2], time.localtime()[3], time.localtime()[4], time.localtime()[5]), 0, 56)
                        else:
                            screen.text("TIME    {:0>2d}:{:0>2d}:{:0>2d}".format((sec // 3600), (sec // 60) - (sec // 3600) * 60, sec % 60), 0, 56)
                    else:
                        screen.fill(0)
                elif screenDisplayMode == 1:
                    lastScreenDisplayMode = 1
                    if screenDisplay:
                        text = []
                        wattsText = ("{:0>6.3f}".format(round(power, 3))).replace(".", "")
                        for i in range(8):
                            text.extend([0x00, 0x00, 0x00, 0x00])
                            for k in range(17):
                                text.append(bigFonts[int(wattsText[0])][i * 17 + k])
                            for k in range(17):
                                text.append(bigFonts[int(wattsText[1])][i * 17 + k])
                            for k in range(9):
                                text.append(bigFonts[10][i * 9 + k])
                            for k in range(17):
                                text.append(bigFonts[int(wattsText[2])][i * 17 + k])
                            for k in range(17):
                                text.append(bigFonts[int(wattsText[3])][i * 17 + k])
                            for k in range(17):
                                text.append(bigFonts[int(wattsText[4])][i * 17 + k])
                            for k in range(30):
                                text.append(bigFonts[11][i * 30 + k])
                        screen.buffer = bytearray(text)
                    else:
                        screen.buffer = bytearray(1024)
                elif screenDisplayMode == 3:
                    lastScreenDisplayMode = 3
                    if screenDisplay:
                        vBat = 0
                        for i in range(5):
                            vBat += vBatAdc.read_u16()
                        vBat = (vBat/5/65535*3+PICO_ADC_SINK_CURRENT/100)*1.5
                        if wifi.isconnected() or wifi.active():
                            middleDotPos = wifi.ifconfig()[0].find(".")
                            middleDotPos = wifi.ifconfig()[0][middleDotPos + 1:].find(".") + middleDotPos + 2
                            screen.text("IP{:>14}".format(wifi.ifconfig()[0][:middleDotPos]), 0, 0)
                            screen.text("{:>15} ".format(wifi.ifconfig()[0][middleDotPos:]), 0, 8)
                        else:
                            screen.text("IP           N/A", 0, 0)
                        screen.text("MAC    "+MACAddress[0:9], 0, 16)
                        screen.text("       "+MACAddress[9:], 0, 24)
                        screen.text("BAT       {:>5.3f}V".format(round(vBat, 3)), 0, 40)
                        screen.text("FW ver  "+PROGRAM_VERSION, 0, 56)
                    else:
                        screen.fill(0)
                screen.show()
                gc.collect()
            await asyncio.sleep(0)
    else:
        while True:
            await asyncio.sleep(0)

if __name__ == "__main__":
    startTime = time.ticks_ms()
    while ledButton.value() and screenButton.value():
        if time.ticks_diff(time.ticks_ms(), startTime) > 1000:
            restore_default_settings()
            break
    load_settings()
    asyncio.run(main())