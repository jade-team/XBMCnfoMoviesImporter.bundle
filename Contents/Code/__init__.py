# coding=utf-8

"""
XBMCnfoMoviesImporter

spec'd from:
https://kodi.wiki/view/NFO_files/Templates

CREDITS:
    Original code author: .......... Harley Hooligan
    Modified v1 by: ................ Guillaume Boudreau
    Modified v2 by:................. JADE Team
    Eden and Frodo compatibility: .. Jorge Amigo
    Cleanup and some extensions: ... SlrG
    Multipart filter idea: ......... diamondsw
    Logo: .......................... CrazyRabbit
    Krypton Rating fix: ............ F4RHaD
    PEP 8 and refactoring: ......... Labrys
    Subtitle support and some fixes: glitch452
"""

from datetime import datetime
import os
import re
import sys
from dateutil.parser import parse

if sys.version_info < (3, 0):
    from htmlentitydefs import name2codepoint
else:
    from html.entities import name2codepoint

    unichr = chr  # chr is already unicode

# PLEX API
preferences = Prefs
element_from_string = XML.ElementFromString
load_file = Core.storage.load
PlexAgent = Agent.Movies
MediaProxy = Proxy.Media
Metadata = MetadataSearchResult
Trailer = TrailerObject


NFO_TEXT_REGEX_1 = re.compile(r"&(?![A-Za-z]+[0-9]*;|#[0-9]+;|#x[0-9a-fA-F]+;)")
NFO_TEXT_REGEX_2 = re.compile(r"^\s*<.*/>[\r\n]+", flags=re.MULTILINE)
RATING_REGEX_1 = re.compile(r"(?:Rated\s)?(?P<mpaa>[A-z0-9-+/.]+(?:\s[0-9]+[A-z]?)?)?")
RATING_REGEX_2 = re.compile(r"\s*\(.*?\)")


def first(iterable, default=None):
    for item in iterable:
        return item
    return default


class NFOReader:
    def __init__(self, nfo_xml):
        self.nfo_xml = nfo_xml

    def read_sets_name(self):
        """
        sets name into a list than return it.
        """
        set_list = []
        for set_el in self.nfo_xml.xpath("set"):
            name_el = first(set_el.xpath("name"), set_el)
            if name_el.text:
                set_list.append(name_el.text)
        return set_list


class XBMCNFO(PlexAgent):
    """
    A Plex Metadata Agent for Movies.

    Uses XBMC nfo files as the metadata source for Plex Movies.
    """

    name = "XBMCnfoMoviesImporter"
    ver = "2.0"
    primary_provider = True
    languages = [Locale.Language.NoLanguage]
    accepts_from = ["com.plexapp.agents.localmedia"]

    # ##### search function #####
    def search(self, results, media, lang):
        log.debug("++++++++++++++++++++++++")
        log.debug("Entering search function")
        log.debug("++++++++++++++++++++++++")

        log.info("{plugin} Version: {number}".format(plugin=self.name, number=self.ver))
        log.debug("Plex Server Version: {number}".format(number=Platform.ServerVersion))

        if preferences["debug"]:
            log.info("Agents debug logging is enabled!")
        else:
            log.info("Agents debug logging is disabled!")

        path1 = media.items[0].parts[0].file
        log.debug("media file: {name}".format(name=path1))

        folder_path = os.path.dirname(path1)
        log.debug("folder path: {name}".format(name=folder_path))

        # Movie name with year from folder
        movie_name_with_year = get_movie_name_from_folder(folder_path, True)
        # Movie name from folder
        movie_name = get_movie_name_from_folder(folder_path, False)

        nfo_names = get_related_files(path1, ".nfo")
        nfo_names.extend(
            [
                # moviename.nfo
                "{movie}.nfo".format(movie=movie_name_with_year),
                "{movie}.nfo".format(movie=movie_name),
                # movie.nfo
                os.path.join(folder_path, "movie.nfo"),
            ]
        )

        # last resort - use first found .nfo
        nfo_files = (f for f in os.listdir(folder_path) if f.endswith(".nfo"))

        try:
            first_nfo = nfo_files.next()
        except StopIteration:
            log.debug("No NFO found in {path!r}".format(path=folder_path))
        else:
            nfo_names.append(os.path.join(folder_path, first_nfo))

        # check possible .nfo file locations
        nfo_file = check_file_paths(nfo_names, ".nfo")

        if nfo_file:
            nfo_text = load_file(nfo_file)
            # work around failing XML parses for things with &'s in
            # them. This may need to go farther than just &'s....
            nfo_text = NFO_TEXT_REGEX_1.sub("&amp;", nfo_text)
            # remove empty xml tags from nfo
            log.debug("Removing empty XML tags from movies nfo...")
            nfo_text = NFO_TEXT_REGEX_2.sub("", nfo_text)

            nfo_text_lower = nfo_text.lower()
            if (
                nfo_text_lower.count("<movie") > 0
                and nfo_text_lower.count("</movie>") > 0
            ):
                # Remove URLs (or other stuff) at the end of the XML file
                nfo_text = "{content}</movie>".format(
                    content=nfo_text.rsplit("</movie>", 1)[0]
                )

                # likely an xbmc nfo file
                try:
                    nfo_xml = element_from_string(nfo_text).xpath("//movie")[0]
                except:
                    log.debug(
                        "ERROR: Cant parse XML in {nfo}."
                        " Aborting!".format(nfo=nfo_file)
                    )
                    return

                # Title
                try:
                    media.name = nfo_xml.xpath("title")[0].text
                except:
                    log.debug(
                        "ERROR: No <title> tag in {nfo}."
                        " Aborting!".format(nfo=nfo_file)
                    )
                    return
                # Sort Title
                try:
                    media.title_sort = nfo_xml.xpath("sorttitle")[0].text
                except:
                    log.debug("No <sorttitle> tag in {nfo}.".format(nfo=nfo_file))
                    pass
                # Year
                try:
                    media.year = int(nfo_xml.xpath("year")[0].text.strip())
                    log.debug("Reading year tag: {year}".format(year=media.year))
                except:
                    pass
                # ID
                try:
                    id = nfo_xml.xpath("tmdbid")[0].text.strip()
                except:
                    id = ""
                    pass
                if len(id) > 2:
                    media.id = id
                    log.debug("ID from nfo: {id}".format(id=media.id))
                else:
                    # if movie id doesn't exist, create
                    # one based on hash of title and year
                    def ord3(x):
                        return "%.3d" % ord(x)

                    id = int("".join(map(ord3, media.name + str(media.year))))
                    id = str(abs(hash(int(id))))
                    media.id = id
                    log.debug("ID generated: {id}".format(id=media.id))

                results.Append(
                    Metadata(
                        id=media.id,
                        name=media.name,
                        year=media.year,
                        lang=lang,
                        score=100,
                    )
                )
                try:
                    log.info(
                        "Found movie information in NFO file:"
                        " title = {nfo.name},"
                        " year = {nfo.year},"
                        " id = {nfo.id}".format(nfo=media)
                    )
                except:
                    pass
            else:
                log.info(
                    "ERROR: No <movie> tag in {nfo}. Aborting!".format(nfo=nfo_file)
                )

    # ##### update Function #####

    def update(self, metadata, media, lang):
        log.debug("++++++++++++++++++++++++")
        log.debug("Entering update function")
        log.debug("++++++++++++++++++++++++")

        log.info("{plugin} Version: {number}".format(plugin=self.name, number=self.ver))
        log.debug("Plex Server Version: {number}".format(number=Platform.ServerVersion))

        if preferences["debug"]:
            log.info("Agents debug logging is enabled!")
        else:
            log.info("Agents debug logging is disabled!")

        poster_data = None
        poster_filename = None
        fanart_data = None
        fanart_filename = None

        path1 = media.items[0].parts[0].file
        log.debug("media file: {name}".format(name=path1))

        folder_path = os.path.dirname(path1)
        log.debug("folder path: {name}".format(name=folder_path))

        is_dvd = os.path.basename(folder_path).upper() == "VIDEO_TS"
        folder_path_dvd = os.path.dirname(folder_path) if is_dvd else None

        # Movie name with year from folder
        movie_name_with_year = get_movie_name_from_folder(folder_path, True)

        # Movie name from folder
        movie_name = get_movie_name_from_folder(folder_path, False)

        # if not preferences["localmediaagent"]:
        poster_names = get_related_files(path1, "-poster.jpg")
        poster_names.extend(
            [
                # Frodo
                "{movie}-poster.jpg".format(movie=movie_name_with_year),
                "{movie}-poster.jpg".format(movie=movie_name),
                os.path.join(folder_path, "poster.jpg"),
            ]
        )
        extend_file_name(poster_names)
        # check possible poster file locations
        poster_filename = check_file_paths(poster_names, "poster")

        if poster_filename:
            poster_data = load_file(poster_filename)
            for key in metadata.posters.keys():
                del metadata.posters[key]
            metadata.posters[poster_filename] = MediaProxy(poster_data)

        fanart_names = get_related_files(path1, "-fanart.jpg")
        fanart_names.extend(
            [
                # Eden / Frodo
                "{movie}-fanart.jpg".format(movie=movie_name_with_year),
                "{movie}-fanart.jpg".format(movie=movie_name),
                os.path.join(folder_path, "fanart.jpg"),
            ]
        )
        extend_file_name(fanart_names)
        # check possible fanart file locations
        fanart_filename = check_file_paths(fanart_names, "fanart")

        if fanart_filename:
            fanart_data = load_file(fanart_filename)
            for key in metadata.art.keys():
                del metadata.art[key]
            metadata.art[fanart_filename] = MediaProxy(fanart_data)

        nfo_names = get_related_files(path1, ".nfo")
        nfo_names.extend(
            [
                "{movie}.nfo".format(movie=movie_name_with_year),
                "{movie}.nfo".format(movie=movie_name),
            ]
        )

        # last resort - use first found .nfo
        nfo_files = (f for f in os.listdir(folder_path) if f.endswith(".nfo"))

        try:
            first_nfo = nfo_files.next()
        except StopIteration:
            log.debug("No NFO file found in {path!r}".format(path=folder_path))
        else:
            nfo_names.append(os.path.join(folder_path, first_nfo))

        # check possible .nfo file locations
        nfo_file = check_file_paths(nfo_names, ".nfo")

        if nfo_file:
            nfo_text = load_file(nfo_file)

            # work around failing XML parses for things with &'s in
            # them. This may need to go farther than just &'s....
            nfo_text = NFO_TEXT_REGEX_1.sub(r"&amp;", nfo_text)

            # remove empty xml tags from nfo
            log.debug("Removing empty XML tags from movies nfo...")
            nfo_text = NFO_TEXT_REGEX_2.sub("", nfo_text)

            nfo_text_lower = nfo_text.lower()

            if (
                nfo_text_lower.count("<movie") > 0
                and nfo_text_lower.count("</movie>") > 0
            ):
                # Remove URLs (or other stuff) at the end of the XML file
                nfo_text = "{content}</movie>".format(
                    content=nfo_text.rsplit("</movie>", 1)[0]
                )

                # likely an xbmc nfo file
                try:
                    nfo_xml = element_from_string(nfo_text).xpath("//movie")[0]
                except:
                    log.debug(
                        "ERROR: Cant parse XML in {nfo}."
                        " Aborting!".format(nfo=nfo_file)
                    )
                    return

                nfo_reader = NFOReader(nfo_xml)

                # remove empty xml tags
                log.debug("Removing empty XML tags from movies nfo...")
                nfo_xml = remove_empty_tags(nfo_xml)

                # Title
                try:
                    metadata.title = nfo_xml.xpath("title")[0].text.strip()
                except:
                    log.debug(
                        "ERROR: No <title> tag in {nfo}."
                        " Aborting!".format(nfo=nfo_file)
                    )
                    return
                # Sort Title
                try:
                    metadata.title_sort = nfo_xml.xpath("sorttitle")[0].text.strip()
                except:
                    log.debug("No <sorttitle> tag in {nfo}.".format(nfo=nfo_file))
                    pass
                # Year
                try:
                    metadata.year = int(nfo_xml.xpath("year")[0].text.strip())
                    log.debug("Set year tag: {year}".format(year=metadata.year))
                except:
                    pass
                # Original Title
                try:
                    metadata.original_title = nfo_xml.xpath("originaltitle")[
                        0
                    ].text.strip()
                except:
                    pass
                # Content Rating
                metadata.content_rating = ""
                # content_rating = {}
                mpaa_rating = ""
                conuntry_rating = ""
                try:
                    mpaa_text = nfo_xml.xpath("./mpaa")[0].text.strip()
                    match = RATING_REGEX_1.match(mpaa_text)
                    if match.group("mpaa"):
                        mpaa_rating = match.group("mpaa")
                        conuntry_rating = mpaa_rating.split("-", 1)
                        if "ES" in mpaa_rating:
                            mpaa_rating = ("es/") + conuntry_rating[1]
                            log.debug("MPAA Rating: " + mpaa_rating)
                        else:
                            mpaa_rating = ("us/") + mpaa_rating
                            log.debug("MPAA Rating: " + mpaa_rating)
                        metadata.content_rating = mpaa_rating
                    else:
                        metadata.content_rating = "NR"
                except:
                    pass
                # Studio
                try:
                    metadata.studio = nfo_xml.xpath("studio")[0].text.strip()
                except:
                    pass
                # Premiere
                release_string = None
                try:
                    log.debug("Reading releasedate tag...")
                    release_string = nfo_xml.xpath("releasedate")[0].text.strip()
                    metadata.originally_available_at = parse(release_string)
                    log.debug(
                        "Releasedate tag is: {value}".format(value=release_string)
                    )
                except:
                    log.debug("No releasedate tag found...")
                    pass
                if not release_string:
                    try:
                        log.debug("Reading premiered tag...")
                        release_string = nfo_xml.xpath("premiered")[0].text.strip()
                        metadata.originally_available_at = parse(release_string)
                        log.debug(
                            "Premiered tag is: {value}".format(value=release_string)
                        )
                    except:
                        log.debug("No premiered tag found...")
                        pass
                # Tagline
                metadata.summary = ""
                try:
                    tagline = nfo_xml.xpath("tagline")[0].text.strip()
                    metadata.tagline = tagline
                except:
                    pass
                # Summary (Outline/Plot)
                try:
                    summary = nfo_xml.xpath("plot")[0].text.strip()
                    metadata.summary = summary
                except:
                    log.debug("Exception on reading summary!")
                    pass
                # Ratings
                nfo_rating = None
                try:
                    nfo_rating = round(
                        float(nfo_xml.xpath("rating")[0].text.replace(",", ".")), 1
                    )
                    log.debug("Movie Rating found: " + str(nfo_rating))
                except:
                    pass
                if not nfo_rating:
                    for ratings in nfo_xml.xpath("ratings"):
                        try:
                            rating = ratings.xpath("rating")[0]
                            nfo_rating = round(
                                float(rating.xpath("value")[0].text.replace(",", ".")),
                                1,
                            )
                        except:
                            log.debug("Can't read rating from .nfo.")
                            nfo_rating = 0.0
                            pass
                metadata.rating = nfo_rating
                # Writers (Credits)
                try:
                    credits = nfo_xml.xpath("credits")
                    metadata.writers.clear()
                    for creditXML in credits:
                        for c in creditXML.text.split("/"):
                            metadata.writers.new().name = c.strip()
                except:
                    pass
                # Directors
                try:
                    directors = nfo_xml.xpath("director")
                    metadata.directors.clear()
                    for directorXML in directors:
                        for d in directorXML.text.split("/"):
                            metadata.directors.new().name = d.strip()
                except:
                    pass
                # Genres
                try:
                    genres = nfo_xml.xpath("genre")
                    metadata.genres.clear()
                    [
                        metadata.genres.add(g.strip())
                        for genreXML in genres
                        for g in genreXML.text.split("/")
                    ]
                    metadata.genres.discard("")
                except:
                    pass
                # Countries
                try:
                    countries = nfo_xml.xpath("country")
                    metadata.countries.clear()
                    [
                        metadata.countries.add(c.strip())
                        for countryXML in countries
                        for c in countryXML.text.split("/")
                    ]
                    metadata.countries.discard("")
                except:
                    pass
                # Collections (Set)
                setname = None
                # Create a pattern to remove 'Series' and 'Collection' from the end of the
                # setname since Plex adds 'Collection' in the GUI already
                setname_pat = re.compile(r"[\s]?(series|collection)$", re.IGNORECASE)
                metadata.collections.clear()

                try:
                    sets_list = nfo_reader.read_sets_name()
                    for setname in sets_list:
                        setname = setname_pat.sub("", setname.strip())
                        if setname:  # skip empty name
                            log.debug("Set name found: " + setname)
                            metadata.collections.add(setname)
                            log.debug("Added Collection: {}".format(setname))
                        else:
                            log.debug("No set name found...")
                except Exception as e:
                    log.error("Raised error when parsing set: {}".format(e))
                # Duration
                try:
                    log.debug(
                        "Trying to read <durationinseconds> tag from .nfo file..."
                    )
                    file_info_xml = element_from_string(nfo_text).xpath("fileinfo")[0]
                    stream_details_xml = file_info_xml.xpath("streamdetails")[0]
                    video_xml = stream_details_xml.xpath("video")[0]
                    runtime = video_xml.xpath("durationinseconds")[0].text.strip()
                    metadata.duration = (
                        int(re.compile("^([0-9]+)").findall(runtime)[0]) * 1000
                    )  # s
                except:
                    try:
                        log.debug("Fallback to <runtime> tag from .nfo file...")
                        runtime = nfo_xml.xpath("runtime")[0].text.strip()
                        metadata.duration = (
                            int(re.compile("^([0-9]+)").findall(runtime)[0]) * 60 * 1000
                        )  # ms
                    except:
                        log.debug("No Duration in .nfo file.")
                        pass
                # Actors
                rroles = []
                metadata.roles.clear()
                for n, actor in enumerate(nfo_xml.xpath("actor")):
                    newrole = metadata.roles.new()
                    try:
                        newrole.name = actor.xpath("name")[0].text
                    except:
                        newrole.name = "Unknown Name " + str(n)
                        pass
                    try:
                        role = actor.xpath("role")[0].text
                        if role in rroles:
                            newrole.role = role + " " + str(n)
                        else:
                            newrole.role = role
                        rroles.append(newrole.role)
                    except:
                        newrole.role = "Unknown Role " + str(n)
                        pass
                    newrole.photo = ""
                    try:
                        newrole.photo = actor.xpath("thumb")[0].text
                        log.debug("linked actor photo: " + newrole.photo)
                    except:
                        log.debug("failed setting linked actor photo!")
                        pass

                log.info("---------------------")
                log.info("Movie nfo Information")
                log.info("---------------------")
                try:
                    log.info("ID: " + str(metadata.guid))
                except:
                    log.info("ID: -")
                try:
                    log.info("Title: " + str(metadata.title))
                except:
                    log.info("Title: -")
                try:
                    log.info("Sort Title: " + str(metadata.title_sort))
                except:
                    log.info("Sort Title: -")
                try:
                    log.info("Year: " + str(metadata.year))
                except:
                    log.info("Year: -")
                try:
                    log.info("Original: " + str(metadata.original_title))
                except:
                    log.info("Original: -")
                try:
                    log.info("Rating: " + str(metadata.rating))
                except:
                    log.info("Rating: -")
                try:
                    log.info("Content: " + str(metadata.content_rating))
                except:
                    log.info("Content: -")
                try:
                    log.info("Studio: " + str(metadata.studio))
                except:
                    log.info("Studio: -")
                try:
                    log.info("Premiere: " + str(metadata.originally_available_at))
                except:
                    log.info("Premiere: -")
                try:
                    log.info("Tagline: " + str(metadata.tagline))
                except:
                    log.info("Tagline: -")
                try:
                    log.info("Summary: " + str(metadata.summary))
                except:
                    log.info("Summary: -")
                log.info("Writers:")
                try:
                    [log.info("\t" + writer.name) for writer in metadata.writers]
                except:
                    log.info("\t-")
                log.info("Directors:")
                try:
                    [log.info("\t" + director.name) for director in metadata.directors]
                except:
                    log.info("\t-")
                log.info("Genres:")
                try:
                    [log.info("\t" + genre) for genre in metadata.genres]
                except:
                    log.info("\t-")
                log.info("Countries:")
                try:
                    [log.info("\t" + country) for country in metadata.countries]
                except:
                    log.info("\t-")
                log.info("Collections:")
                try:
                    [log.info("\t" + collection) for collection in metadata.collections]
                except:
                    log.info("\t-")
                try:
                    log.info(
                        "Duration: {time} min".format(time=metadata.duration // 60000)
                    )
                except:
                    log.info("Duration: -")
                log.info("Actors:")
                for actor in metadata.roles:
                    try:
                        log.info("\t{actor.name} > {actor.role}".format(actor=actor))
                    except:
                        try:
                            log.info("\t{actor.name}".format(actor=actor))
                        except:
                            log.info("\t-")
                    log.info("---------------------")
            else:
                log.info(
                    "ERROR: No <movie> tag in {nfo}." " Aborting!".format(nfo=nfo_file)
                )
            return metadata


xbmcnfo = XBMCNFO

# -- LOG ADAPTER -------------------------------------------------------------


class PlexLogAdapter(object):
    """
    Adapts Plex Log class to standard python logging style.

    This is a very simple remap of methods and does not provide
    full python standard logging functionality.
    """

    debug = Log.Debug
    info = Log.Info
    warn = Log.Warn
    error = Log.Error
    critical = Log.Critical
    exception = Log.Exception


class XBMCLogAdapter(PlexLogAdapter):
    """
    Plex Log adapter that only emits debug statements based on preferences.
    """

    @staticmethod
    def debug(*args, **kwargs):
        """
        Selective logging of debug message based on preference.
        """
        if preferences["debug"]:
            Log.Debug(*args, **kwargs)


log = XBMCLogAdapter


# -- HELPER FUNCTIONS --------------------------------------------------------

VIDEO_FILE_BASE_REGEX = re.compile(r"(?is)\s*-\s*(cd|dvd|disc|disk|part|pt|d)\s*[0-9]$")


def get_base_file(video_file):
    """
    Get a Movie's base filename.

    This strips the video file extension and any CD / DVD or Part
    information from the video's filename.

    :param video_file: filename to be processed
    :return: string containing base file name
    """
    # split the filename and extension
    base, extension = os.path.splitext(video_file)
    del extension  # video file's extension is not used
    # Strip CD / DVD / Part information from file name
    base = VIDEO_FILE_BASE_REGEX.sub("", base)
    # Repeat a second time
    base = VIDEO_FILE_BASE_REGEX.sub("", base)
    return base


def get_related_file(video_file, file_extension):
    """
    Get a file related to the Video with a different extension.

    :param video_file: the filename of the associated video
    :param file_extension: the related files extension
    :return: a filename for a related file
    """
    return get_base_file(video_file) + file_extension


RELATED_DIRS = {
    "/",
    "/NFO/",
    "/nfo/",
}


def get_related_files(video_file, file_extension):
    """
    Get a file related to the Video with a different extension.
    Support alternate subdirectories for related files.

    :param video_file: the filename of the associated video
    :param file_extension: the related files extension
    :return: a filename for a related file
    """

    folder_path, file_name = os.path.split(video_file)
    results = []
    for i in RELATED_DIRS:
        results.append(get_base_file(folder_path + i + file_name) + file_extension)
    return results


MOVIE_NAME_REGEX = re.compile(r" \(.*\)")


def get_movie_name_from_folder(folder_path, with_year):
    """
    Get the name of the movie from the folder.

    :param folder_path:
    :param with_year:
    :return:
    """
    # Split the folder into a list of paths
    folder_split = os.path.normpath(folder_path).split(os.sep)

    if folder_split[-1] == "VIDEO_TS":  # If the folder is from a DVD
        # Strip the VIDEO_TS folder
        base = os.path.join(*folder_split[1 : len(folder_split) - 1])
        name = folder_split[-2]
    else:
        base = os.path.join(*folder_split)
        name = folder_split[-1]

    if with_year:  # then apply the MOVIE_NAME_REGEX to strip year information
        name = MOVIE_NAME_REGEX.sub("", name)

    # Append the Movie name from folder to the end of the path
    movie_name = os.path.join(base, name)
    log.debug(
        "Movie name from folder{with_year}: {name}".format(
            with_year=" (with year)" if with_year else "",
            name=movie_name,
        )
    )
    return movie_name


def check_file_paths(file_names, file_type=None):
    """
    CHeck a list of file names and return the first one found.

    :param file_names: An iterable of file names to check
    :param file_type: (Optional) Type of file searched for. Used for logging.
    :return: a valid filename or None
    """
    for filename in file_names:
        log.debug("Trying {name}".format(name=filename))
        if os.path.exists(filename):
            log.info(
                "Found {type} file {name}".format(
                    type=file_type if file_type else "a",
                    name=filename,
                )
            )
            return filename
    else:
        log.info(
            "No {type} file found! Aborting!".format(
                type=file_type if file_type else "valid"
            )
        )


def remove_empty_tags(document):
    """
    Removes empty XML tags.

    :param document: An HTML element object.
        see: http://lxml.de/api/lxml.etree._Element-class.html
    :return:
    """
    empty_tags = []
    for xml_tag in document.iter("*"):
        if not (len(xml_tag) or (xml_tag.text and xml_tag.text.strip())):
            empty_tags.append(xml_tag.tag)
            xml_tag.getparent().remove(xml_tag)
    log.debug(
        "Empty XMLTags removed: {number} {tags}".format(
            number=len(empty_tags) or None, tags=sorted(set(empty_tags)) or ""
        )
    )
    return document


UNESCAPE_REGEX = re.compile("&#?\w+;")


def unescape(markup):
    """
    Removes HTML or XML character references and entities from a text.
    Copyright:
        http://effbot.org/zone/re-sub.htm October 28, 2006 | Fredrik Lundh
    :param markup: The HTML (or XML) source text.
    :return: The plain text, as a Unicode string, if necessary.
    """

    def fix_up(match):
        """
        Convert a match from a character reference or named entity to unicode.

        :param match:  A regex match to attempt to convert to unicode
        :return: unescaped character or original text
        """
        element = match.group(0)
        if element.startswith("&#"):  # character reference
            start, base = (3, 16) if element.startswith("&#x") else (2, 10)
            try:
                return unichr(int(element[start:-1], base))
            except ValueError:
                pass
        else:  # named entity
            try:
                element = unichr(name2codepoint[element[1:-1]])
            except KeyError:
                pass
        return element  # leave as is

    return UNESCAPE_REGEX.sub(fix_up, markup)


def extend_file_name(file_names):
    file_names.extend(list(map(replace_jpg_png, file_names)))


def replace_jpg_png(path):
    return path.replace("jpg", "png")
