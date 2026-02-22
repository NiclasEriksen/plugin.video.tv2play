import sys
from urllib.parse import parse_qsl, urlencode
import xbmcgui
import xbmc
import xbmcaddon
import xbmcplugin
from resources.lib.logging import LOG
from resources.lib.globals import G
from resources.lib.view.prompt import Prompt
from resources.lib.view.player import Player
from resources.lib.api.api import PlayAPI
from resources.lib.api.models import Structure, Pages, Node
from resources.lib.api.exception import ConcurrencyLimitViolationException, HTTPException

class Router:
    ACTION_STRUCTURE = "structure"
    ACTION_SERIE = "serie"
    ACTION_SEASON = "season"
    ACTION_SERIE_VIDEO = "show"
    ACTION_VIDEO = "video"
    ACTION_PAGE = "page"
    ACTION_SEARCH = "search"

    def initialize(self, argv):
        G.init_globals(argv) # Has to be executed first!
        if G.FIRST_RUN:
            self.prompt = Prompt()
            self.api = PlayAPI()
            self.pages = Pages()
        G.FIRST_RUN = False
        LOG.info(argv)
        self.params = dict(parse_qsl(argv[2][1:]))
        self.url = argv[0]

    def login(self):
        try:
            is_authenticated = self.api.is_authenticated()
            if is_authenticated:
                LOG.info("Already authenticated")
                return True
            if self.api.login_with_cookie():
                LOG.info("Logged in with cookies.")
                return True
            username = G.ADDON.getSetting("username")
            password = G.ADDON.getSetting("password")
            if username == "" or password == "":
                username, password = self.prompt.get_credentials()
                if self.api.login(username, password):
                    LOG.info("Logged in with typed credentials.")
                    return True
                self.prompt.display_message("Error", "The supplied credentials are invalid.")
                return False
            else:
                if self.api.login(username, password):
                    LOG.info("Loggged in with saved credentials.")
                    return True
                self.prompt.display_message("Error", "The saved credentials are invalid, change them in the addon's settings.")
                return False
        except HTTPException as exp:
            self.prompt.display_message(exp.title, exp.msg)
            return False

    def route(self):
        if not self.login():
            return
        if self.params:
            action = self.params["action"]
            param = self.params.get("param", None)

            if action == self.ACTION_PAGE:
                self.list_page_content(param)

            elif action == self.ACTION_STRUCTURE:
                self.list_structure_content(param)

            elif action == self.ACTION_SERIE:
                self.list_seasons(param)

            elif action == self.ACTION_SERIE_VIDEO:
                videos = self.api.get_serie_videos(param)
                self.list_videos(videos)

            elif action == self.ACTION_SEASON:
                videos = self.api.get_season_videos(param)
                self.list_videos(videos)
                
            elif action == self.ACTION_VIDEO:
                self.play_video(param)

            elif action == self.ACTION_SEARCH:
                self.search()

            else:
                raise ValueError("Invalid paramstring: {0}!".format(self.params))
        else:
            self.list_pages()

    def add_list_item(self, action, label="", info={}, art={}, param="", is_folder=True):
        list_item = xbmcgui.ListItem(label=label)
        list_item.setInfo("video", info)
        list_item.setArt(art)
        url = self.get_url(action=action, param=param)
        if not is_folder:
            list_item.setProperty("IsPlayable", "True")
        xbmcplugin.addDirectoryItem(G.HANDLE, url, list_item, is_folder)


    def add_directory(self, action, node, param=""):
        label = node.get_title()
        info = {"title": node.get_title(),
                "mediatype": "video",
                "plot": node.get_plot()}
        thumb = node.get_thumb()
        art = {"thumb": thumb,
                "icon": thumb,
                "fanart": thumb
            }
        self.add_list_item(action, label=label, info=info, art=art,param=param)

    def add_video(self, action, video, param=""):
        label = video.get_title()
        LOG.info("WATCHED: " + str(video.get_playcount()))
        info = {"title": video.get_title(),
                "mediatype": "video",
                "plot": video.get_plot(),
                "date": video.get_publication_date(),
                "episode": video.get_episode(),
                "season": video.get_season(),
                "playcount": video.get_playcount()
            }

        if video.in_progress():
            position, duration = video.get_progress()
            info["position"] = position
            info["duration"] = duration

        thumb = video.get_thumb()
        art = { "thumb": thumb,
                "icon": thumb,
                "fanart": thumb
            }
        self.add_list_item(action,label=label, info=info, art=art, param=param, is_folder=False)


    def add_station(self, action, station, param=""):
        label = station.get_title()
        info = {"title": station.get_title(),
                "mediatype": "video",
                "plot": station.get_plot(),
            }
        thumb = station.get_thumb()
        art = { "thumb": thumb,
                "icon": thumb,
                "fanart": thumb
            }
        self.add_list_item(action,label=label, info=info, art=art, param=param, is_folder=False)

    def list_pages(self):
        for page in self.pages.pages:
            self.add_directory(self.ACTION_PAGE, page, param=page.get_id())
        self.add_directory(self.ACTION_SEARCH, Node(title="Search", plot="Search all TV2 Play content"))
        xbmcplugin.endOfDirectory(G.HANDLE)
    
    def list_page_content(self, page_id):
        LOG.info("Open page: " + page_id)
        for subpage in self.api.get_subpages(page_id):
            self.add_directory(self.ACTION_PAGE, subpage, param=subpage.get_id())
        for structure in self.api.get_structures(page_id):
            self.add_directory(self.ACTION_STRUCTURE, structure, param=structure.get_id())
        if page_id == "/live":
            for station in self.api.get_stations():
                self.add_station(self.ACTION_VIDEO, station, param=station.get_id())
        xbmcplugin.endOfDirectory(G.HANDLE)

    def get_url(self, **kwargs):
        """
        Create a URL for calling the plugin recursively from the given set of keyword arguments.

        :param kwargs: "argument=value" pairs
        :type kwargs: dict
        :return: plugin call URL
        :rtype: str
        """
        return "{0}?{1}".format(self.url, urlencode(kwargs))

    def list_structure_content(self, structure_id):
        LOG.info("Enter structure: " + structure_id)
        videos, series = self.api.get_structure_content(structure_id)
        for s in series:
            LOG.info("Has seasons: " + str(s.has_seasons()))
            if s.has_seasons():
                self.add_directory(self.ACTION_SERIE, s, param=s.get_id())
            else:
                self.add_directory(self.ACTION_SERIE_VIDEO, s, param=s.get_id())
                
        for v in videos:
            self.add_video(self.ACTION_VIDEO, v, param=v.get_id())
            xbmcplugin.addSortMethod(G.HANDLE, xbmcplugin.SORT_METHOD_DATE)
        xbmcplugin.endOfDirectory(G.HANDLE)


    def list_videos(self, videos):
        """
        """
        for v in videos:
            self.add_video(self.ACTION_VIDEO, v, param=v.get_id())
            xbmcplugin.addSortMethod(G.HANDLE, xbmcplugin.SORT_METHOD_DATE)
        xbmcplugin.endOfDirectory(G.HANDLE)

    def list_seasons(self, serie_guid):
        LOG.info("Listing seasons: " + serie_guid)
        for season in self.api.get_seasons(serie_guid):
            self.add_directory(self.ACTION_SEASON, season, param=season.get_id())
        xbmcplugin.endOfDirectory(G.HANDLE)

    def play_video(self, video_guid):
        """
        """
        LOG.info("Play video: " + video_guid)
        try:
            playback = self.api.get_playback(video_guid)
        except ConcurrencyLimitViolationException as exp:
            self.prompt.display_message(exp.title, exp.msg)
        except HTTPException as exp:
            self.prompt.display_message(exp.title, exp.msg)
        else:
            if playback == None:
                self.prompt.display_message("Error", "An error occured")
                return 
            player = Player(playback)
            player.play_video()

    def search(self):
        search_phrase = self.prompt.get_input("Search")
        if search_phrase == "" or search_phrase == None:
            return
        LOG.info("Searching for: " + search_phrase)
        try:
            (series, episodes, movies) = self.api.search(search_phrase)
        except HTTPException as exp:
            self.prompt.display_message(exp.title, exp.msg)
        else:
            for serie in series:
                self.add_directory(self.ACTION_SERIE_VIDEO, serie, param=serie.get_id())
            for episode in episodes:
                self.add_video(self.ACTION_VIDEO, episode, episode.get_id())
            for movie in movies:
                self.add_video(self.ACTION_VIDEO, movie, movie.get_id())
        xbmcplugin.endOfDirectory(G.HANDLE)

ROUTER = Router()
