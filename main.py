import math
from argparse import ArgumentParser
from datetime import datetime, timedelta

import pandas as pd
from pandas import read_csv


def time_elapsed(time_str: str) -> timedelta:
    basetime = datetime(1900, 1, 1)
    try:
        return datetime.strptime(time_str, '%H:%M:%S.%f') - basetime
    except ValueError:
        return datetime.strptime(time_str, '%M:%S.%f') - basetime


def sec_to_time(elapsed: float) -> str:
    hr, rem1 = divmod(elapsed, 3600)
    min, sec = divmod(rem1, 60)
    tenths, rem1 = divmod(sec, 10)
    return '{:02}:{:02}:{:02}.{:1}'.format(int(hr), int(min), int(sec), int(tenths))


def compute_lap_seconds(x: pd.Series) -> float:
    return x['Lap Seconds'] if not math.isnan(x['Lap Seconds']) else x['Elapsed Seconds']


def is_empty(col: pd.Series) -> bool:
    return col.apply(lambda x: is_nan(x)).all(axis=0)


def is_nan(x) -> bool:
    return x is None or x == '-' or (isinstance(x, float) and math.isnan(x))


def update_time(x: pd.Series) -> str:
    max_laps = len([ij for ij, c in enumerate(x.index) if 'Lap' in c])
    completed_laps = len([ij for ij in range(1, max_laps+1) if not is_nan(x[f'Lap {ij}'])])
    return f'-{max_laps-completed_laps} laps' if max_laps > completed_laps else x[f'Split {max_laps}']


def fix_col_data(x: pd.Series) -> pd.Series:
    if 'Leg' in x.name:
        x = x.apply(lambda y: '' if is_nan(y) else y)
    elif 'Lap' in x.name or 'Split' in x.name:
        x = x.apply(lambda y: '-' if is_nan(y) else y)
    return x


def get_category(name: str, signup_data: pd.DataFrame) -> str:
    try:
        match_row = signup_data[signup_data['Full Name'] == name]
        return match_row['Category'].values[0]
    except IndexError:
        print(f"Could not find category for person name={name}, assuming ???")
        return "I DUNNO"


def get_bib(name: str, signup_data: pd.DataFrame) -> str:
    try:
        match_row = signup_data[signup_data['Full Name'] == name]
        return match_row['Bib'].values[0]
    except IndexError:
        print(f"Could not find bib for person name={name}, assuming nil")
        return ""


def main():
    arg_parse = ArgumentParser()
    arg_parse.add_argument(
        "input_file", help="Tab delimited txt file of complete results"
    )
    arg_parse.add_argument('--signup', help='Signup list for bibs/team names/categories')
    args = arg_parse.parse_args()

    signup_data = read_csv(args.signup, sep='\t', dtype=str)
    signup_data['Full Name'] = signup_data.apply(lambda x: f'{x["First Name"]} {x["Last Name"]}', axis=1)

    data = read_csv(args.input_file, sep="\t", dtype=str)

    leg_columns = [col_name for col_name in data.columns if "leg" in col_name.lower()]
    lap_columns = [
        col_name for col_name in data.columns if "lap" in col_name.lower()
    ]

    updated_data = pd.DataFrame(columns=data.columns)

    # Find all solos and split from teams
    for row in range(data.shape[0]):
        category = data["Category"][row]
        team_name = data["Team name"][row]
        if "solo" not in category.lower() or "DNS" == data['Time'][row]:
            updated_data = updated_data.append(data.loc[row, :], ignore_index=True)
            continue
        else:
            leg_names: pd.Series = data.loc[row, leg_columns]
            is_valid = leg_names.map(
                lambda x: not isinstance(x, float) or not math.isnan(x)
            )
            valid_legs: pd.Series = leg_names.loc[is_valid]
            valid_laps: pd.Series = data.loc[row, lap_columns[0: len(valid_legs)]]

            lap_with_name = pd.concat(
                [valid_laps.reset_index(drop=True), valid_legs.reset_index(drop=True)],
                ignore_index=True,
                axis=1,
            )
            lap_with_name.rename({0: 'Lap', 1: 'Team name'}, axis=1, inplace=True)
            lap_with_name['Lap Seconds'] = lap_with_name.apply(lambda x: time_elapsed(x.Lap).total_seconds(), axis=1)
            lap_with_name['Elapsed Seconds'] = lap_with_name['Lap Seconds'].cumsum()
            lap_with_name['Split Time'] = lap_with_name.apply(lambda x: sec_to_time(x['Elapsed Seconds']), axis=1)
            lap_with_name['Bib'] = lap_with_name.apply(lambda x: get_bib(x['Team name'], signup_data), axis=1)
            lap_with_name['Category'] = lap_with_name.apply(lambda x: get_category(x['Team name'], signup_data), axis=1)
            lap_with_name['Team name'] = lap_with_name.apply(lambda x: f"{x['Team name']} ({team_name})", axis=1)

            leg_groups = lap_with_name.groupby('Team name')

            single_rider = all([leg == valid_legs[0] for leg in valid_legs])
            if single_rider:
                updated_data = updated_data.append(data.loc[row, :], ignore_index=True)
                continue
            else:
                # print(leg_groups)
                for group_name, group_df in leg_groups:
                    group_df.reset_index(inplace=True, drop=True)
                    group_df['Lap Seconds'] = group_df['Elapsed Seconds'].diff()
                    group_df['Lap Seconds'] = group_df.apply(lambda x: compute_lap_seconds(x), axis=1)
                    group_df['Lap Time'] = group_df.apply(lambda x: sec_to_time(x['Lap Seconds']), axis=1)

                    new_row = pd.DataFrame(columns=data.columns)
                    new_row.loc[0, 'Bib'] = group_df['Bib'][0]
                    new_row.loc[0, 'Team name'] = group_name
                    new_row.loc[0, 'Category'] = category
                    new_row.loc[0, 'Start'] = data['Start'][row]
                    new_row.loc[0, 'Time'] = group_df['Split Time'][len(group_df)-1]
                    for leg_idx in range(group_df.shape[0]):
                        new_row.loc[0, f'Leg {leg_idx+1}'] = group_name
                        new_row.loc[0, f'Split {leg_idx + 1}'] = group_df.loc[leg_idx, 'Split Time']
                        new_row.loc[0, f'Lap {leg_idx + 1}'] = group_df.loc[leg_idx, 'Lap Time']

                    updated_data = updated_data.append(new_row, ignore_index=True)

    # Remove unnecessary laps, legs, splits
    empty_cols = updated_data.apply(lambda col: is_empty(col), axis=0)
    # Filter to just empty
    empty_cols = empty_cols[empty_cols]
    updated_data: pd.DataFrame = updated_data.drop(columns=empty_cols.index)

    # Rewrite time column
    updated_data['Time'] = updated_data.apply(lambda x: update_time(x), axis=1)
    updated_data = updated_data.apply(lambda col: fix_col_data(col), axis=0)

    # Rewrite the file
    updated_data.to_csv(args.input_file.replace('.txt','_fixed.txt'), sep='\t', index=False)


if __name__ == "__main__":
    main()
