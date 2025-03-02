# preprocessing/data_processing.py
import pandas as pd
import numpy as np

def load_data(file_path):
    """Load and preprocess the football match data."""
    try:
        matches = pd.read_csv(file_path)
        
        # Check if essential columns exist, if not create empty DataFrame with required columns
        required_columns = ['date', 'team', 'opponent', 'venue', 'result', 'gf', 'ga', 'sh', 'sot']
        
        if not all(col in matches.columns for col in required_columns):
            # Create empty DataFrame with required columns
            matches = pd.DataFrame(columns=required_columns)
            
        # Ensure date is datetime
        if 'date' in matches.columns:
            matches['date'] = pd.to_datetime(matches['date'])
            
        # Add time column if missing
        if 'time' not in matches.columns:
            matches['time'] = '15:00'  # Default time
            
        return matches
    except FileNotFoundError:
        # Create and return empty DataFrame with required columns
        return pd.DataFrame(columns=['date', 'team', 'opponent', 'venue', 'result', 'gf', 'ga', 'sh', 'sot', 'time'])

def encode_categorical_features(df):
    """Convert categorical variables to numerical codes."""
    # Generate team codes
    teams = sorted(df['team'].unique())
    team_code_dict = {team: idx for idx, team in enumerate(teams)}
    df['team_code'] = df['team'].map(team_code_dict)
    
    # Encode venue
    df['venue_code'] = df['venue'].map({'Home': 1, 'Away': 0})
    
    # Encode opponent
    df['opp_code'] = df['opponent'].map(team_code_dict)
    
    # Extract hour from time (with error handling)
    if 'time' in df.columns:
        try:
            df['hour'] = df['time'].str.split(':').str[0].astype('int')
        except:
            df['hour'] = 15  # Default to 3 PM if there's an error
    else:
        df['hour'] = 15  # Default hour
    
    # Add day code (day of week)
    df['day_code'] = df['date'].dt.dayofweek
    
    # Create target variable (win = 1, draw/loss = 0)
    df['target'] = (df['result'] == 'W').astype('int')
    
    return df

def calculate_rolling_averages(group, cols, new_cols):
    """Calculate rolling averages for key metrics with error handling."""
    group = group.sort_values('date')
    
    # Check which columns are available
    available_cols = [col for col in cols if col in group.columns]
    available_new_cols = [f"{col.split('_')[0]}_rolling" for col in new_cols if col.split('_')[0] in available_cols]
    
    if available_cols:
        # Calculate rolling averages for available columns
        rolling_stats = group[available_cols].rolling(3, closed='left').mean()
        group[available_new_cols] = rolling_stats[available_cols]
    
    # Fill NaN values with mean or default values
    for col in available_new_cols:
        if col in group.columns:
            if group[col].isna().all():
                base_col = col.split('_')[0]
                if base_col in group.columns:
                    group[col] = group[col].fillna(group[base_col].mean())
                else:
                    default_values = {
                        'gf': 1.5, 'ga': 1.0, 'sh': 12.0, 'sot': 5.0,
                        'dist': 15.0, 'fk': 2.0, 'pk': 0.5, 'pkatt': 0.5
                    }
                    group[col] = group[col].fillna(default_values.get(base_col, 0))
            else:
                group[col] = group[col].fillna(group[col].mean())
    
    return group

def prepare_model_data(df):
    """Prepare data for model training with all preprocessing steps."""
    if df.empty:
        # Return empty DataFrame with expected columns
        return pd.DataFrame(columns=[
            'date', 'team', 'opponent', 'venue', 'result', 'team_code', 
            'venue_code', 'opp_code', 'hour', 'day_code', 'target',
            'gf_rolling', 'ga_rolling', 'sh_rolling', 'sot_rolling'
        ])
    
    # Apply initial encoding
    df = encode_categorical_features(df)
    
    # Identify available stat columns in the DataFrame
    all_possible_cols = ['gf', 'ga', 'sh', 'sot', 'dist', 'fk', 'pk', 'pkatt']
    available_cols = [col for col in all_possible_cols if col in df.columns]
    
    if not available_cols:
        # If no stat columns are found, add default ones
        for col in ['gf', 'ga', 'sh', 'sot']:
            if col not in df.columns:
                df[col] = df['result'].map({'W': 2.0, 'D': 1.0, 'L': 0.5})  # Default values
        available_cols = ['gf', 'ga', 'sh', 'sot']
    
    # Calculate rolling average column names
    new_cols = [f"{c}_rolling" for c in available_cols]
    
    # Group by team and apply rolling averages
    try:
        matches_rolling = df.groupby('team').apply(
            lambda x: calculate_rolling_averages(x, available_cols, new_cols)
        )
        matches_rolling = matches_rolling.droplevel('team')
        matches_rolling.index = range(matches_rolling.shape[0])
    except Exception as e:
        print(f"Error calculating rolling averages: {e}")
        # Add basic rolling average columns with default values
        for col in ['gf_rolling', 'ga_rolling', 'sh_rolling', 'sot_rolling']:
            base_col = col.split('_')[0]
            if base_col in df.columns:
                df[col] = df[base_col]
            else:
                default_values = {'gf': 1.5, 'ga': 1.0, 'sh': 12.0, 'sot': 5.0}
                df[col] = default_values.get(base_col, 1.0)
        matches_rolling = df
    
    return matches_rolling