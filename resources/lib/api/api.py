import requests
import time
from datetime import datetime
from resources.lib.api.cookies import CookieFile
from resources.lib.globals import G
from bs4 import BeautifulSoup
from ..logging import LOG
from resources.lib.logging import LOG
from .exception import LoginException, HTTPException, ConcurrencyLimitViolationException, NoTypeException
from .models import Video, PlayBack, Serie, Page, Structure, Station, User, Season
from .concurrency import ConcurrencyLock
from urllib.parse import urlparse, parse_qs

class PlayAPI:
    def __init__(self):
        self.api_url = "https://api.ovp.tv2.dk"
        self.auth_url = "https://play.tv2.dk/api/user"
        self.cookie_file = CookieFile(G.DATA_PATH, G.COOKIES_FILE_NAME)
        self.concurrency_lock = ConcurrencyLock(G.CONCURRENCY_FILE)
        self.session = requests.session()
        self.user = None

    def login(self, username, password):
        login_url = self.auth_url + "/login?return_url=/"
        response = self.session.get(login_url)

        url_params = parse_qs(urlparse(response.url).query)

        url = "https://auth.tv2.dk/usernamepassword/login"
        data = {
                "username": username,
                "password": password,
                "connection": "TV-2-AWS-Login",
                "state" : url_params["state"][0],
                "client_id" : url_params["client"][0],
                "scope": url_params["scope"][0],
                "tenant": "tv2dk-prod"
            }

        response = self.session.post(url, data=data)
        if response.status_code != 200:
            return False

        soup = BeautifulSoup(response.text, "html.parser")
        data = {}
        for i in soup.find_all("input"):
            data[i.get("name")] = i.get("value")
        url = soup.form.get("action")
        response = self.session.post(url, data=data)

        response = self.session.get(self.auth_url)
        if response.status_code == 200 and response.json()["user"] != None:
            LOG.info("Successful login - Saving cookies")

            cookies = self.session.cookies.copy()
            cookies.pop("play.sid") # Remove session id
            self.cookie_file.save(self.session.cookies)

            self.user = User(response.json()["user"])
            return True
        LOG.warning("Login failed")
        return False

    def login_with_cookie(self):
        front_page = "https://play.tv2.dk/forside"
        cookies = self.cookie_file.load()
        try:
            self.session.get(front_page, cookies=cookies)
            response = self.session.get(self.auth_url, cookies=cookies)
        except requests.exceptions.ConnectionError:
            raise HTTPException()
        else:
            if response.status_code == 200 and response.json()["user"] != None:
                LOG.info("Authenticated with cookies")
                self.user = User(response.json()["user"])
                self.session.headers.update(self.__get_headers())
                return True
            LOG.warning("Failed to authenticate with cookies with status_code :" + str(response.status_code))
            LOG.info("Deleting cookies")
            self.cookie_file.delete()
            return False
    
    def is_authenticated(self):
        return self.user != None

    def __get_headers(self):
        LOG.info("Auth token: " + self.user.access_token)
        headers = {
            "authorization": self.user.access_token,
            "Host": "api.ovp.tv2.dk",
            "Origin": "https://play.tv2.dk",
            "DNT": "1"
        }
        return headers
    
    def __do_request(self, query, **kwargs):
        data = {"query": query, "variables": kwargs}
        headers = self.__get_headers()
        response = self.session.post(self.api_url, json=data, headers=headers)
        response_data = response.json().get("data", None)
        errors = response.json().get("errors", None)
        if errors:
            for e in errors:
                data = e.get("data", {})
                message = """
                    Message: %s - 
                    Type: %s -
                    Debug: %s
                """ % (e.get("message", "No Message"), data.get( "type", "No type" ), data.get( "debug", "No debug" ))
                LOG.error(message)
                exception_type = e.get("data", {}).get("type", None)
                if exception_type == HTTPException.TYPE:
                    raise HTTPException()
                elif exception_type == ConcurrencyLimitViolationException.TYPE:
                    raise ConcurrencyLimitViolationException()
                else:
                    raise NoTypeException()
            return None
        if response.status_code == 200 and response_data != None:
            return response_data

    def get_subpages(self, page_path):
        query = """
            query PageQuery($path: String!, $limit: Int){
                    page(path: $path, platform: play_web){
                id
                title
                subpages(limit: $limit) {
                  nodes {
                    title
                    id
                    path
                  }
                }
              }
            }
        """
        data = self.__do_request(query, path=page_path, limit=20)["page"]["subpages"]
        if data != None:
            pages = []
            for p in data["nodes"]:
                pages.append(Page(p))
            return pages
        return []
    
    def get_structures(self, page_path):
        query = """
            query PageQuery($path: String!){
                    page(path: $path, platform: play_web){
                id
                title
                structures {
                  nodes {
                    title
                    id
                  }
                }
              }
            }
        """
        structures = []
        data = self.__do_request(query, path=page_path)["page"]
        if data["structures"] != None:
            for s in data["structures"]["nodes"]:
                structures.append(Structure(s))
        return structures

    def get_structure_content(self, structure_id):
        query = """
            query play_web_content_Structure(
                $entitySort: SortType
                $structureId: ID!
                $limit: Int
            ) {
                structure(id: $structureId) {
                    ...StructureFragment
                }
            }
            fragment StructureFragment on Structure {
                entities(
                    sort: $entitySort
                    limit: $limit
                ) {
                    pageInfo {
                        totalCount
                    }
                    nodes {
                        ...StructureEntityFragment
                    }
                }
            }

            fragment StructureEntityFragment on Entity {
                id
                guid
                type
                title: presentationTitle
                description: presentationDescription
                thumbnail: presentationArt {
                    url
                }
                ... on Series {
                        seasons(limit: $limit, order: asc){
                        nodes {
                            seasonNumber
                        }
                    }
                }
            }
        """
        data = self.__do_request(query, limit=9999, entitySort="popular", structureId=structure_id)
        if data != None:
            series = []
            videos = []
            for s in data["structure"]["entities"]["nodes"]:
                if s == None:
                    continue
                if s["type"] == "series":
                    series.append(Serie(s))
                elif s["type"] == "episode":
                    videos.append(Video(s))
            return videos, series
        return [],[]

    def get_seasons(self, serie_guid):
        query = """
            query serieSeasonQuery(
                $serieGuid: String!
                $limit: Int
            ){
                entity(guid: $serieGuid) {
                    id
                    guid
                    type
                    originalTitle: title
                    title: presentationTitle
                    subtitle: presentationSubtitle
                    description: presentationDescription
                    thumbnail: presentationArt {
                        type
                        url
                    }
                    ... on Series {
                            seasons(limit: $limit, order: asc){
                            nodes {
                                id
                                seasonNumber
                                title
                            }
                        }
                    }
                }
            }
        """
        data = self.__do_request(query, limit=9999, serieGuid=serie_guid)
        if data != None:
            seasons = []
            thumbnail = data["entity"]["thumbnail"]["url"]
            plot = data["entity"]["description"]
            for s in data["entity"]["seasons"]["nodes"]:
                if s == None:
                    continue
                season = Season(s, plot, thumbnail)
                seasons.append(season)
            return seasons
        return []
    
    def get_serie_videos(self, serie_guid):
        query = """
            query play_web_content_SeriesEpisodeEntityPage_LatestEpisodes(
              $seriesGuid: String!
              $limit: Int
            ) {
              series: entity(type: series, guid: $seriesGuid) {
                ... on Series {
                  episodes(limit: $limit) {
                    ...EpisodeListFragment
                  }
                }
              }
            }
            fragment EpisodeListFragment on EpisodeList {
              pageInfo {
                totalCount
              }
              nodes {
                episodeNumber
                seasonNumber
                firstPublicationDate
                lastPublicationDate
                watched
                ... on Progressable {
                  progress {
                    position
                    duration
                  }
                }
                ...StructureEntityFragment
              }
            }
            fragment StructureEntityFragment on Entity {
              id
              guid
              type
              title
              subtitle: presentationSubtitle
              description: presentationDescription
              thumbnail: presentationArt {
                url
              }
            }
        """
        data = self.__do_request(query, limit=200, seriesGuid=serie_guid)
        if data != None:
            videos = []
            for v in data["series"]["episodes"]["nodes"]:
                videos.append(Video(v))
            return videos
        return None

    def get_season_videos(self, season_id):
        query = """
            query SeasonEpisodesQuery($seasonId: ID!, $limit: Int) {
              season(id: $seasonId) {
                id
                title
                episodes(limit: $limit) {
                  ...EpisodeListFragment
                }
              }
            }
            fragment EpisodeListFragment on EpisodeList {
              nodes {
                episodeNumber
                firstPublicationDate
                lastPublicationDate
                watched
                duration
                ... on Progressable {
                  progress {
                    position
                    duration
                  }
                }
                ...StructureEntityFragment
              }
            }
            fragment StructureEntityFragment on Entity {
              id
              guid
              type
              title
              subtitle: presentationSubtitle
              description: presentationDescription
              thumbnail: presentationArt {
                type
                url
                __typename
              }
              ... on Episode {
                art(type: "alt_promotion") {
                  nodes {
                    url
                  }
                }
              }
            }
        """
        data = self.__do_request(query, limit=999, seasonId=season_id)
        if data != None:
            videos = []
            for v in data["season"]["episodes"]["nodes"]:
                videos.append(Video(v))
            return videos
        return None


    def get_playback(self, guid):
        query = """
        query GetPlayback(
            $guid: String!
            $clientId: String!
        ) {
          playback(
            guid: $guid
            format: ["application/dash+xml"]
            platform: play_web
          ) {
            subtitles {
              useAsDefault
            }
            progress {
              position
            }
            pid
            smil(clientId: $clientId) {
              meta {
                nodes {
                  name
                  content
                }
              }
              video {
                src
                type
              }
              securityLicense {
                url
                token
              }
            }
          }
        }
        """
        if self.concurrency_lock.is_locked():
            response_code = self.concurrency_lock.unlock(self.session)
            LOG.info("Unlocking concurrency lock - Status: " + str(response_code))
        try:
            data = self.__do_request(query, guid=guid, clientId=self.concurrency_lock.get_client_id())
            self.concurrency_lock.set_meta(data["playback"]["smil"]["meta"]["nodes"])
            if data != None and data["playback"] != None:
                return PlayBack(data["playback"])
        except HTTPException as exp:
            LOG.warning("Http Exception")
            raise exp
        except ConcurrencyLimitViolationException as exp:
            LOG.warning("Concurrency Limit Violation")
            raise exp
        return None
    
    def get_stations(self):
        query = """
            query play_web_content_StationsWithEpgData(
              $epgDate: String
              $fetchEntities: Boolean!)
            {
              stations {
                nodes {
                  id
                  type
                  description
                  guid
                  title
                  presentationArt{
                    url
                 }
                epgEntries(date: $epgDate) {
                    nodes {
                      title
                      startUnix: start
                      stopUnix: stop
                      entity @include(if: $fetchEntities) {
                        type
                        references {
                          web
                        }
                      }
                    }
                  }
                }
              }
            }
        """
        data = self.__do_request(query, fetchEntities=True)
        if data != None and data["stations"]["nodes"] != None:
            stations = []
            for station in data["stations"]["nodes"] :
                stations.append(Station(station))
            return stations
        return None
    
    def search(self, search_phrase):
        query = """
            query play_web_content_SearchStructuresWithData(
              $search_phrase: String!
              $limit: Int
            ) {
              series: search(query: $search_phrase, entityTypes: series) {
                ...SearchStructureFragment
                __typename
              }
              episode: search(query: $search_phrase, entityTypes: episode) {
                ...SearchStructureFragment
                __typename
              }
              movie: search(query: $search_phrase, entityTypes: movie) {
                ...SearchStructureFragment
                __typename
              }
            }
            fragment SearchStructureFragment on SearchPanelStructure {
              entities(limit: $limit) {
                nodes {
                  id
                  guid
                  type
                  originalTitle: title
                  title: presentationTitle
                  subtitle: presentationSubtitle
                  description: presentationDescription
                  thumbnail: presentationArt {
                    url
                  }
                }
              }
            }
        """
        series = []
        episodes = []
        movies = []
        data = self.__do_request(query, search_phrase=search_phrase, limit=15)
        if data != None:
            for serie in data["series"]["entities"]["nodes"]:
                series.append(Serie(serie))
            for episode in data["episode"]["entities"]["nodes"]:
                episodes.append(Video(episode))
            for movie in data["movie"]["entities"]["nodes"]:
                movies.append(Video(movie))
        return (series, episodes, movies)





