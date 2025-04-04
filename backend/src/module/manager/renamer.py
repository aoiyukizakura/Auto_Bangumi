import logging
import re
import os

from module.conf import settings
from module.downloader import DownloadClient
from module.models import EpisodeFile, Notification, SubtitleFile
from module.parser import TitleParser

logger = logging.getLogger(__name__)


class Renamer(DownloadClient):
    def __init__(self):
        super().__init__()
        self._parser = TitleParser()
        self.check_pool = {}

    @staticmethod
    def print_result(torrent_count, rename_count):
        if rename_count != 0:
            logger.info(
                f"Finished checking {torrent_count} files' name, renamed {rename_count} files."
            )
        logger.debug(f"Checked {torrent_count} files")

    @staticmethod
    def gen_path(
            file_info: EpisodeFile | SubtitleFile, bangumi_name: str, method: str
    ) -> str:
        season = f"0{file_info.season}" if file_info.season < 10 else file_info.season
        episode = (
            f"0{file_info.episode}" if file_info.episode < 10 else file_info.episode
        )
        if method == "none" or method == "subtitle_none":
            return file_info.media_path
        elif method == "pn":
            return f"{file_info.title} S{season}E{episode}{file_info.suffix}"
        elif method == "advance":
            return f"{bangumi_name} S{season}E{episode}{file_info.suffix}"
        elif method == "normal":
            logger.warning("[Renamer] Normal rename method is deprecated.")
            return file_info.media_path
        elif method == "subtitle_pn":
            return f"{file_info.title} S{season}E{episode}.{file_info.language}{file_info.suffix}"
        elif method == "subtitle_advance":
            return f"{bangumi_name} S{season}E{episode}.{file_info.language}{file_info.suffix}"
        else:
            logger.error(f"[Renamer] Unknown rename method: {method}")
            return file_info.media_path

    def rename_file(
            self,
            torrent_name: str,
            media_path: str,
            bangumi_name: str,
            method: str,
            season: int,
            _hash: str,
            **kwargs,
    ):
        ep = self._parser.torrent_parser(
            torrent_name=torrent_name,
            torrent_path=media_path,
            season=season,
        )
        if ep:
            new_path = self.gen_path(ep, bangumi_name, method=method)
            if media_path != new_path:
                if new_path not in self.check_pool.keys():
                    if self.rename_torrent_file(
                        _hash=_hash, old_path=media_path, new_path=new_path
                    ):
                        return Notification(
                            official_title=bangumi_name,
                            season=ep.season,
                            episode=ep.episode,
                        )
        else:
            logger.warning(f"[Renamer] {media_path} parse failed")
            if settings.bangumi_manage.remove_bad_torrent:
                self.delete_torrent(hashes=_hash)
        return None

    def rename_collection(
            self,
            media_list: list[str],
            bangumi_name: str,
            season: int,
            method: str,
            _hash: str,
            **kwargs,
    ):
        for media_path in media_list:
            if self.is_ep(media_path):
                ep = self._parser.torrent_parser(
                    torrent_path=media_path,
                    season=season,
                )
                if ep:
                    new_path = self.gen_path(ep, bangumi_name, method=method)
                    if media_path != new_path:
                        renamed = self.rename_torrent_file(
                            _hash=_hash, old_path=media_path, new_path=new_path
                        )
                        if not renamed:
                            logger.warning(f"[Renamer] {media_path} rename failed")
                            # Delete bad torrent.
                            if settings.bangumi_manage.remove_bad_torrent:
                                self.delete_torrent(_hash)
                                break
    def link_collection(
            self,
            media_list: list[str],
            bangumi_name: str,
            season: int,
            method: str,
            _hash: str,
            **kwargs,
    ):
        for media_path in media_list:
            if self.is_ep(media_path):
                ep = self._parser.torrent_parser(
                    torrent_path=media_path,
                    season=season,
                )
                if ep:
                    new_path = self.gen_path(ep, bangumi_name, method=method)
                    if media_path != new_path:
                        if new_path not in self.check_pool.keys():
                            try:
                                # 创建软链接而不是重命名文件
                                os.link(media_path, new_path)
                                logger.info(f"[Renamer] Created link: {new_path} -> {media_path}")
                            except FileExistsError:
                                logger.warning(f"[Renamer] Link already exists: {new_path}")
                            except FileNotFoundError:
                                logger.error(f"[Renamer] File not found: {media_path}")
                            except OSError as e:
                                logger.error(f"[Renamer] Failed to create link for {media_path}: {e}")
                                # 删除错误种子
                                if settings.bangumi_manage.remove_bad_torrent:
                                    self.delete_torrent(_hash)
                                    break

    def rename_subtitles(
            self,
            subtitle_list: list[str],
            torrent_name: str,
            bangumi_name: str,
            season: int,
            method: str,
            _hash,
            **kwargs,
    ):
        method = "subtitle_" + method
        for subtitle_path in subtitle_list:
            sub = self._parser.torrent_parser(
                torrent_path=subtitle_path,
                torrent_name=torrent_name,
                season=season,
                file_type="subtitle",
            )
            if sub:
                new_path = self.gen_path(sub, bangumi_name, method=method)
                if subtitle_path != new_path:
                    renamed = self.rename_torrent_file(
                        _hash=_hash, old_path=subtitle_path, new_path=new_path
                    )
                    if not renamed:
                        logger.warning(f"[Renamer] {subtitle_path} rename failed")

    def rename(self) -> list[Notification]:
        # Get torrent info
        logger.debug("[Renamer] Start rename process.")
        rename_method = settings.bangumi_manage.rename_method
        torrents_info = self.get_torrent_info()
        renamed_info: list[Notification] = []
        for info in torrents_info:
            media_list, subtitle_list = self.check_files(info)
            bangumi_name, season = self._path_to_bangumi(info.save_path)
            kwargs = {
                "torrent_name": info.name,
                "bangumi_name": bangumi_name,
                "method": rename_method,
                "season": season,
                "_hash": info.hash,
            }
            # Rename single media file
            if len(media_list) == 1:
                notify_info = self.rename_file(media_path=media_list[0], **kwargs)
                if notify_info:
                    renamed_info.append(notify_info)
                # Rename subtitle file
                if len(subtitle_list) > 0:
                    self.rename_subtitles(subtitle_list=subtitle_list, **kwargs)
            # Rename collection
            elif len(media_list) > 1:
                logger.info("[Renamer] Start rename collection")
                self.link_collection(media_list=media_list, **kwargs)
                if len(subtitle_list) > 0:
                    self.rename_subtitles(subtitle_list=subtitle_list, **kwargs)
                self.set_category(info.hash, "BangumiCollection")

                # 添加 .ignore 文件到集合文件夹
                ignore_file_path = os.path.join(info.save_path, info.name, ".ignore")
                try:
                    with open(ignore_file_path, "w") as ignore_file:
                        ignore_file.write("# This file prevents media library scanning.\n")
                    logger.info(f"[Renamer] Created .ignore file in collection folder: {ignore_file_path}")
                except OSError as e:
                    logger.error(f"[Renamer] Failed to create .ignore file in {info.save_path}: {e}")
            else:
                logger.warning(f"[Renamer] {info.name} has no media file")
        logger.debug("[Renamer] Rename process finished.")
        return renamed_info

    def compare_ep_version(self, torrent_name: str, torrent_hash: str):
        if re.search(r"v\d.", torrent_name):
            pass
        else:
            self.delete_torrent(hashes=torrent_hash)


if __name__ == "__main__":
    from module.conf import setup_logger

    settings.log.debug_enable = True
    setup_logger()
    with Renamer() as renamer:
        renamer.rename()
