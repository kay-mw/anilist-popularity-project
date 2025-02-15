import json
from io import StringIO
from typing import Literal

import numpy as np
import pandas as pd
from azure.storage.blob import BlobServiceClient


def get_blob(
    blob_service_client: BlobServiceClient, container_id: str, blob_name: str
) -> StringIO:
    blob_client = blob_service_client.get_blob_client(
        container=container_id, blob=blob_name
    )
    downloader = blob_client.download_blob(max_concurrency=1, encoding="UTF-8")
    blob_text = downloader.readall()
    csv = StringIO(f"""{blob_text}""")
    return csv


def list_to_dict(genre_list: list[str]) -> dict:
    genre_dict = {}
    for i, genre in enumerate(genre_list):
        genre_dict[i] = genre

    return genre_dict


def parse_genres(df: pd.DataFrame) -> pd.DataFrame:
    df["genres"] = df["genres"].apply(eval)
    df["genres"] = df["genres"].apply(list_to_dict)
    df["genres"] = df["genres"].apply(json.dumps)

    return df


def process_format_info(
    blob_service_client: BlobServiceClient,
    container_id: str,
    blobs: list[str],
    format: Literal["anime", "manga"],
    position=0,
) -> pd.DataFrame:
    format_info = get_blob(blob_service_client, container_id, blobs[position])
    format_info = pd.read_csv(
        format_info,
        sep=",",
        dtype={
            "Unnamed: 0": int,
            f"{format}_id": int,
            "average_score": int,
            "genres": pd.StringDtype(),
            "title_romaji": str,
            "popularity": int,
        },
    )
    format_info.drop(labels="Unnamed: 0", axis=1, inplace=True)
    format_info = parse_genres(format_info)

    return format_info


def process_user_info(
    blob_service_client: BlobServiceClient,
    container_id: str,
    blobs: list[str],
    position: int,
) -> pd.DataFrame:
    user_info = get_blob(blob_service_client, container_id, blobs[position])
    user_info = pd.read_csv(
        user_info,
        sep=",",
        dtype={
            "Unnamed: 0": int,
            "user_id": int,
            "user_name": str,
        },
        parse_dates=["request_date"],
        date_format="%Y-%m-%d %H:%M:%S",
    )
    user_info.drop(labels="Unnamed: 0", axis=1, inplace=True)

    return user_info


def process_user_anime_score(
    blob_service_client: BlobServiceClient,
    container_id: str,
    blobs: list[str],
    insert_date: str,
    position: int,
) -> pd.DataFrame:
    user_anime_score = get_blob(blob_service_client, container_id, blobs[position])
    user_anime_score = pd.read_csv(
        user_anime_score,
        sep=",",
        dtype={
            "Unnamed: 0": int,
            "user_id": int,
            "anime_id": int,
            "user_score": int,
        },
    )
    user_anime_score.drop(labels="Unnamed: 0", axis=1, inplace=True)
    user_anime_score["start_date"] = insert_date
    user_anime_score["end_date"] = np.nan

    return user_anime_score


def process_user_manga_score(
    blob_service_client: BlobServiceClient,
    container_id: str,
    blobs: list[str],
    insert_date: str,
    position: int,
) -> pd.DataFrame:
    user_manga_score = get_blob(blob_service_client, container_id, blobs[position])
    user_manga_score = pd.read_csv(
        user_manga_score,
        sep=",",
        dtype={
            "Unnamed: 0": int,
            "user_id": int,
            "manga_id": int,
            "user_score": int,
        },
    )
    user_manga_score.drop(labels="Unnamed: 0", axis=1, inplace=True)
    user_manga_score["start_date"] = insert_date
    user_manga_score["end_date"] = np.nan

    return user_manga_score


def read_anime_and_manga(
    blob_service_client: BlobServiceClient,
    container_id: str,
    blobs: list[str],
    insert_date: str,
) -> tuple[
    list[pd.DataFrame],
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    anime_info = process_format_info(
        blob_service_client, container_id, blobs, format="anime"
    )

    manga_info = process_format_info(
        blob_service_client, container_id, blobs, position=1, format="manga"
    )

    user_anime_score = process_user_anime_score(
        blob_service_client, container_id, blobs, insert_date, position=2
    )

    user_info = process_user_info(blob_service_client, container_id, blobs, position=3)

    user_manga_score = process_user_manga_score(
        blob_service_client, container_id, blobs, insert_date, position=4
    )

    dfs = [anime_info, manga_info, user_anime_score, user_info, user_manga_score]
    return dfs, anime_info, manga_info, user_anime_score, user_info, user_manga_score


def read_anime(
    blob_service_client: BlobServiceClient,
    container_id: str,
    blobs: list[str],
    insert_date: str,
) -> tuple[list[pd.DataFrame], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    anime_info = process_format_info(
        blob_service_client, container_id, blobs, format="anime"
    )

    user_anime_score = process_user_anime_score(
        blob_service_client, container_id, blobs, insert_date, position=1
    )

    user_info = process_user_info(blob_service_client, container_id, blobs, position=2)

    dfs = [anime_info, user_anime_score, user_info]
    return dfs, anime_info, user_anime_score, user_info


def read_manga(
    blob_service_client: BlobServiceClient,
    container_id: str,
    blobs: list[str],
    insert_date: str,
) -> tuple[list[pd.DataFrame], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    manga_info = process_format_info(
        blob_service_client, container_id, blobs, position=0, format="manga"
    )

    user_info = process_user_info(blob_service_client, container_id, blobs, position=1)

    user_manga_score = process_user_manga_score(
        blob_service_client, container_id, blobs, insert_date, position=2
    )

    dfs = [manga_info, user_info, user_manga_score]
    return dfs, manga_info, user_info, user_manga_score
