import xbmc

class Logger:
    def __log(self, msg, level):
        xbmc.log("[plugin.video.tv2play] " + str(msg), level=level)

    def error(self, msg):
        self.__log(msg, xbmc.LOGERROR)

    def info(self, msg):
        self.__log(msg, xbmc.LOGINFO)

    def warning(self, msg):
        self.__log(msg, xbmc.LOGWARNING)

LOG = Logger()

