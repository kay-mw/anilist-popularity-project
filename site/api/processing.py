import asyncio
import datetime as dt
import os
from typing import Literal
from urllib.parse import quote_plus

import pandas as pd
import requests.exceptions
from sqlalchemy import create_engine

from api.funcs import fetch_anilist_data, fetch_anilist_data_async, load_query


def get_id(username: str) -> int:
    query_get_id = load_query("get_id.gql")
    variables_get_id = {"name": username}
    json_response = None
    try:
        json_response, _ = fetch_anilist_data(query_get_id, variables_get_id)
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            raise ValueError(f"Username {username} not found.")
        if e.response.status_code == 429:
            raise ValueError(
                "Oops! AniList is a bit overloaded at the moment, please try again later."
            )

    if json_response is None:
        raise ValueError(f"Failed to fetch data for {username}.")

    anilist_id = json_response["data"]["User"]["id"]

    return anilist_id


def get_user_data(
    username: str, anilist_id: int, format: Literal["anime", "manga"]
) -> tuple[pd.DataFrame, pd.DataFrame, list[int]]:
    json_response = None
    response_header = None
    query_user = load_query(f"{format}_user.gql")

    variables_user = {"page": 1, "id": anilist_id}
    try:
        json_response, response_header = fetch_anilist_data(query_user, variables_user)
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 429:
            raise ValueError(
                "Oops! AniList is a bit overloaded at the moment, please try again later."
            )

    if json_response is None or response_header is None:
        raise ValueError(f"Failed to fetch data for {username}.")

    user_score = pd.json_normalize(
        json_response,
        record_path=["data", "Page", "users", "statistics", f"{format}", "scores"],
        meta=[["data", "Page", "users", "id"]],
    )

    if user_score.empty:
        raise ValueError(f"AniList returned no {format} for {username}.")

    user_score = user_score.explode("mediaIds", ignore_index=True)
    user_score["mediaIds"] = user_score["mediaIds"].astype(int)

    user_score.rename(
        columns={
            "mediaIds": f"{format}_id",
            "data.Page.users.id": "user_id",
            "score": "user_score",
        },
        inplace=True,
    )

    if max(user_score["user_score"]) <= 10:
        user_score["user_score"] = user_score["user_score"].apply(lambda x: x * 10)
    else:
        pass

    # NOTE: Make user info table
    user_info = pd.json_normalize(json_response, record_path=["data", "Page", "users"])
    user_info.drop(f"statistics.{format}.scores", axis=1, inplace=True)

    user_info = pd.concat([user_info, response_header], axis=1)
    user_info.rename(
        columns={0: "request_date", "id": "user_id", "name": "user_name"},
        inplace=True,
    )
    user_info["request_date"] = pd.to_datetime(
        user_info["request_date"], format="%a, %d %b %Y %H:%M:%S %Z"
    ).dt.tz_localize(None)

    id_list = user_score[f"{format}_id"].values.tolist()
    return user_score, user_info, id_list


def get_format_info(
    username: str, id_list: list[int], format: Literal["anime", "manga"]
) -> pd.DataFrame:
    async def main():
        response_ids = None
        format_info = pd.DataFrame()

        variables_format = {"page": 1, "id_in": id_list}
        query_format = load_query("media.gql")

        while True:
            try:
                response_ids = await fetch_anilist_data_async(
                    query_format, variables_format
                )
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429:
                    raise ValueError(
                        "Oops! AniList is a bit overloaded at the moment, please try again later."
                    )

            if response_ids == None:
                raise ValueError(f"Failed to fetch data for {username}.")

            page_df = pd.json_normalize(
                response_ids, record_path=["data", "Page", "media"]
            )
            format_info = pd.concat([format_info, page_df], ignore_index=True)

            if not response_ids["data"]["Page"]["pageInfo"]["hasNextPage"]:
                break

            variables_format["page"] += 1

        return format_info

    format_info = asyncio.run(main())

    format_info.rename(
        columns={
            "averageScore": "average_score",
            "title.romaji": "title_romaji",
            "id": f"{format}_id",
        },
        inplace=True,
    )

    return format_info


def check_nulls(
    format_info: pd.DataFrame,
    user_score: pd.DataFrame,
    format: Literal["anime", "manga"],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    null_ids = list(format_info.loc[format_info.isna().any(axis=1)][f"{format}_id"])
    if len(null_ids) > 0:
        format_info.dropna(axis=0, inplace=True)
        user_score = user_score[~user_score[f"{format}_id"].isin(null_ids)]
    format_info = format_info.astype({"average_score": int})

    return format_info, user_score


def round_scores(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if (df["user_score"] % 10 == 0).all():
        df["average_score"] = 10 * round(df["average_score"] / 10)
        all_scores = list(range(10, 101, 10))
        new_rows = pd.DataFrame(
            {
                "score": all_scores,
                "user_count": 0,
                "average_count": 0,
            }
        )
    else:
        df["average_score"] = 5 * round(df["average_score"] / 5)
        all_scores = list(range(10, 101, 5))
        new_rows = pd.DataFrame(
            {
                "score": all_scores,
                "user_count": 0,
                "average_count": 0,
            }
        )

    return df, new_rows


def create_plot_data(df: pd.DataFrame, fill_df: pd.DataFrame) -> list[dict]:
    user_count = df.value_counts("user_score").reset_index()
    average_count = df.value_counts("average_score").reset_index()

    user_count = user_count.rename(columns={"count": "user_count"})
    average_count = average_count.rename(columns={"count": "average_count"})

    average_count["average_score"] = average_count["average_score"].astype(int)

    plot_data = user_count.merge(
        right=average_count,
        how="outer",
        left_on="user_score",
        right_on="average_score",
    )

    plot_data["user_score"] = plot_data["user_score"].fillna(plot_data["average_score"])
    plot_data = plot_data.fillna(0.0).astype({"average_count": int})

    plot_data = plot_data.drop("average_score", axis=1).rename(
        columns={"user_score": "score"}
    )

    plot_data = pd.concat([plot_data, fill_df], ignore_index=True)
    plot_data = plot_data.drop_duplicates(subset=["score"], keep="first")

    plot_data = plot_data.sort_values(by="score", ascending=True).reset_index(drop=True)
    plot_json = plot_data.to_dict(orient="records")

    return plot_json


def create_table(df: pd.DataFrame) -> list[dict]:
    score_table = df[
        ["title_romaji", "score_diff", "user_score", "average_score"]
    ].copy()
    score_table["abs_score_diff"] = abs(score_table.loc[:, "score_diff"])
    score_table["average_score"] = score_table["average_score"].astype(int)
    score_table = score_table.sort_values(by="abs_score_diff", ascending=False)
    score_table = score_table.reset_index(drop=True)
    score_table = score_table.drop(labels="abs_score_diff", axis=1)
    table_dict = score_table.to_dict(orient="records")

    return table_dict


def create_genre_data(genre_df: pd.DataFrame) -> list[dict]:
    genre_df = (
        genre_df.round({"weighted_average": 1, "weighted_user": 1, "weighted_diff": 2})
        .reset_index(drop=True)
        .drop(
            labels=["average_score", "user_score", "count"],
            axis=1,
        )
        .sort_values("weighted_diff", ascending=False, key=abs)
    )
    genre_dict = genre_df.to_dict(orient="records")

    return genre_dict


def create_abs_avg_plot_data(
    format: Literal["anime", "manga"], abs_score_diff: float, avg_score_diff: float
) -> tuple[list[dict], list[dict]]:
    existing_data_path = f"./api/existing_{format}_data.parquet"
    file_exists = os.path.isfile(existing_data_path)

    if file_exists:
        last_queried = dt.datetime.now() - dt.datetime.fromtimestamp(
            os.path.getmtime(existing_data_path)
        )
    else:
        last_queried = dt.timedelta(days=0)

    if (not file_exists) or (last_queried >= dt.timedelta(days=1)):
        connection_string = os.environ["AZURE_ODBC"]
        connection_url = (
            f"mssql+pyodbc:///?odbc_connect={quote_plus(connection_string)}"
        )
        engine = create_engine(connection_url)

        with engine.connect() as connection:
            query = f"""
                SELECT {format}_id, user_score, user_id
                FROM user_{format}_score
                WHERE end_date IS NULL 
                AND start_date IS NOT NULL;
            """
            existing_user_score = pd.read_sql(sql=query, con=connection)

            query = f"""
                SELECT {format}_id, average_score
                FROM {format}_info;
            """
            existing_format_info = pd.read_sql(sql=query, con=connection)

            existing_merged_dfs = existing_user_score.merge(
                existing_format_info, on=f"{format}_id", how="left"
            )
            existing_merged_dfs.to_parquet(existing_data_path)

    def diff_buckets(df: pd.DataFrame, calc_type: Literal["abs", "avg"]) -> list[dict]:
        df["score_diff"] = df["user_score"] - df["average_score"]

        if calc_type == "abs":
            df[f"{calc_type}_score_diff"] = (
                df["user_score"] - df["average_score"]
            ).abs()
        else:
            df[f"{calc_type}_score_diff"] = df["user_score"] - df["average_score"]

        agg_data = df.groupby(by="user_id", as_index=False).agg(
            {f"{calc_type}_score_diff": "mean"}
        )
        agg_data[f"{calc_type}_score_diff"] = (
            agg_data[f"{calc_type}_score_diff"].round().astype(int)
        )
        agg_data = pd.DataFrame(
            agg_data.value_counts(f"{calc_type}_score_diff", sort=False)
        ).reset_index()

        if calc_type == "abs":
            if round(abs_score_diff) not in agg_data[f"{calc_type}_score_diff"].values:
                agg_data.loc[len(agg_data)] = [round(abs_score_diff), 1]
        else:
            if round(avg_score_diff) not in agg_data[f"{calc_type}_score_diff"].values:
                agg_data.loc[len(agg_data)] = [round(avg_score_diff), 1]

        agg_data = agg_data.sort_values(by=f"{calc_type}_score_diff")
        agg_data = agg_data.to_dict(orient="records")

        return agg_data

    existing_user_df = pd.read_parquet(existing_data_path)

    abs_data = diff_buckets(df=existing_user_df, calc_type="abs")
    avg_data = diff_buckets(df=existing_user_df, calc_type="avg")

    return abs_data, avg_data


def create_obscurity_data(
    format: Literal["anime", "manga"], format_df: pd.DataFrame
) -> tuple[list[dict], int]:
    existing_data_path = f"./api/existing_{format}_pop_data.parquet"
    file_exists = os.path.isfile(existing_data_path)
    user_pop = int(round(format_df["popularity"].mean()))

    if file_exists:
        last_queried = dt.datetime.now() - dt.datetime.fromtimestamp(
            os.path.getmtime(existing_data_path)
        )
    else:
        last_queried = dt.timedelta(days=0)

    if (not file_exists) or (last_queried >= dt.timedelta(days=1)):
        connection_string = os.environ["AZURE_ODBC"]
        connection_url = (
            f"mssql+pyodbc:///?odbc_connect={quote_plus(connection_string)}"
        )
        engine = create_engine(connection_url)

        with engine.connect() as connection:
            query = f"""
                SELECT AVG(f.popularity) AS average_popularity
                FROM {format}_info AS f
                LEFT JOIN user_{format}_score uf
                ON f.{format}_id = uf.{format}_id
                WHERE uf.end_date IS NULL
                AND uf.start_date IS NOT NULL
                AND f.popularity IS NOT NULL
                GROUP BY user_id;
            """
            pop_df = pd.read_sql(sql=query, con=connection)

            pop_df.to_parquet(existing_data_path)

    existing_df = pd.read_parquet(existing_data_path)

    if user_pop not in existing_df["average_popularity"].values:
        existing_df.loc[len(existing_df)] = user_pop

    existing_df = existing_df.sort_values(by="average_popularity", ascending=False)

    pop_dict = existing_df.to_dict(orient="records")

    return pop_dict, user_pop
