# api/main.py
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import pandas as pd
import io
import sys
import os
import traceback
from ml.model import train_ensemble_model
from ml.model_versioning import ModelVersionTracker
# ml/ensemble_model.py
# Line 8:


# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from preprocessing.data_processing import load_data, prepare_model_data
from ml.model import train_prediction_model, prepare_match_prediction_data

app = FastAPI(title="Football Prediction API")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Models for API requests and responses
class MatchPredictionRequest(BaseModel):
    home_team: str
    away_team: str
    match_date: str
    match_time: str
    team_to_predict: str  # "home" or "away"
    # Form stats
    goals_for: float
    goals_against: float
    shots: float
    shots_on_target: float
    # Optional additional stats
    distance: Optional[float] = None
    free_kicks: Optional[float] = None
    penalties: Optional[float] = None
    penalty_attempts: Optional[float] = None

class PredictionResponse(BaseModel):
    team: str
    opponent: str
    win_probability: float
    prediction: str
    key_factors: List[dict]

# Load data and model
MODEL_PATH = "../models/trained_model.pkl"
DATA_PATH = "../data/matches.csv"

@app.on_event("startup")
async def startup_event():
    try:
        # Try to load existing data
        app.state.data = load_data(DATA_PATH)
        app.state.processed_data = prepare_model_data(app.state.data) if not app.state.data.empty else None
        
        # Train both models
        app.state.model = train_prediction_model(app.state.processed_data) if app.state.processed_data is not None else None
        app.state.ensemble_model = train_ensemble_model(app.state.processed_data) if app.state.processed_data is not None else None
        
        print("Models trained successfully")
    except Exception as e:
        print(f"Error during startup: {e}")
        # Initialize with empty data
        app.state.data = pd.DataFrame(columns=['date', 'team', 'opponent', 'venue', 'result', 'gf', 'ga', 'sh', 'sot', 'time'])
        app.state.processed_data = None
        app.state.model = None
        app.state.ensemble_model = None

@app.get("/")
async def root():
    return {"message": "Football Prediction System API"}
@app.get("/model-versions/")
async def get_model_versions(model_type: str = None):
    """Return list of model versions, optionally filtered by type"""
    version_tracker = ModelVersionTracker()
    versions = version_tracker.get_model_versions(model_type)
    return versions

@app.get("/model-versions/{version_name}")
async def get_model_version_details(version_name: str):
    """Return detailed information about a specific model version"""
    version_tracker = ModelVersionTracker()
    details = version_tracker.get_version_details(version_name)
    
    if not details:
        raise HTTPException(status_code=404, detail=f"Model version '{version_name}' not found")
    
    return details

@app.get("/model-performance-comparison/")
async def get_model_performance_comparison():
    """Compare performance metrics across model versions"""
    version_tracker = ModelVersionTracker()
    
    # Get all model versions
    all_versions = version_tracker.get_model_versions()
    
    # Filter to versions with metrics
    versions_with_metrics = []
    for version in all_versions:
        details = version_tracker.get_version_details(version['version_name'])
        if details and details.get('metrics'):
            version_data = {
                'version_name': version['version_name'],
                'model_type': version['model_type'],
                'creation_date': version['creation_date'],
                'metrics': details['metrics']
            }
            versions_with_metrics.append(version_data)
    
    # Group by model type for comparison
    comparison = {}
    for version in versions_with_metrics:
        model_type = version['model_type']
        if model_type not in comparison:
            comparison[model_type] = []
        comparison[model_type].append(version)
    
    return {
        'model_comparisons': comparison,
        'overview': {
            'total_versions': len(all_versions),
            'versions_with_metrics': len(versions_with_metrics),
            'model_types': list(comparison.keys())
        }
    }
@app.get("/teams/")
async def get_teams():
    """Return list of teams in the dataset"""
    try:
        print("Teams endpoint called")
        
        if not hasattr(app.state, 'data') or app.state.data is None or app.state.data.empty:
            # Return some default teams if no data is available
            default_teams = ["Manchester United", "Arsenal", "Liverpool", "Chelsea", "Tottenham"]
            print(f"No data available, returning default teams: {default_teams}")
            return default_teams
        
        if 'team' not in app.state.data.columns:
            print("No team column in data")
            return []
        
        teams = app.state.data['team'].unique().tolist()
        print(f"Returning teams: {teams}")
        return sorted(teams)
    except Exception as e:
        print(f"Error in teams endpoint: {e}")
        import traceback
        traceback.print_exc()
        # Return empty list instead of error
        return []

@app.get("/team-stats/{team_name}")
async def get_team_stats(team_name: str):
    """Return statistics for a specific team"""
    if not hasattr(app.state, 'data') or app.state.data is None or app.state.data.empty:
        raise HTTPException(status_code=404, detail="No data available. Please upload data first.")
    
    if 'team' not in app.state.data.columns or team_name not in app.state.data['team'].values:
        raise HTTPException(status_code=404, detail=f"Team {team_name} not found in data")
    
    team_data = app.state.data[app.state.data['team'] == team_name]
    
    # Calculate basic stats
    matches = team_data.to_dict('records')
    
    # Create summary stats
    wins = sum(1 for match in matches if match.get('result') == 'W')
    draws = sum(1 for match in matches if match.get('result') == 'D')
    losses = sum(1 for match in matches if match.get('result') == 'L')
    
    return {
        "matches": matches,
        "stats": {
            "matches_played": len(matches),
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "win_percentage": round(wins / len(matches) * 100, 1) if matches else 0
        }
    }

@app.get("/head-to-head/{team1}/{team2}")
async def get_head_to_head(team1: str, team2: str):
    """Return head to head statistics between two teams"""
    if not hasattr(app.state, 'data') or app.state.data is None or app.state.data.empty:
        raise HTTPException(status_code=404, detail="No data available. Please upload data first.")
    
    # Sample data structure since we can't compute real head-to-head stats without more data
    return {
        "stats": {
            "team1": {"attack": 75, "defense": 70, "possession": 65, "form": 80, "homeAdvantage": 75},
            "team2": {"attack": 65, "defense": 75, "possession": 60, "form": 70, "awayPerformance": 60}
        },
        "history": []  # This would contain previous match results
    }

# api/main.py - Updated data-insights endpoint with team parameter

# api/main.py - Replace data-insights endpoint

@app.get("/data-insights/")
@app.get("/data-insights/{team_name}")
async def get_data_insights(team_name: str = None):
    print(f"Data insights requested for team: {team_name}")
    
    if not hasattr(app.state, 'data') or app.state.data is None or app.state.data.empty:
        return {"error": "No data available"}
    
    data = app.state.data
    
    # Filter by team if specified
    if team_name and team_name != "all" and 'team' in data.columns:
        filtered_data = data[data['team'] == team_name]
        if filtered_data.empty:
            filtered_data = data  # Use all data if filter results in empty set
    else:
        filtered_data = data
    
    # Calculate result distribution
    result_counts = {'W': 0, 'D': 0, 'L': 0}
    if 'result' in filtered_data.columns:
        for result in ['W', 'D', 'L']:
            result_counts[result] = int(sum(filtered_data['result'] == result))
    
    total_matches = sum(result_counts.values()) or 1  # Avoid division by zero
    
    # Calculate percentages
    result_distribution = [
        {"name": "Win", "value": round(result_counts.get('W', 0) / total_matches * 100, 1)},
        {"name": "Draw", "value": round(result_counts.get('D', 0) / total_matches * 100, 1)},
        {"name": "Loss", "value": round(result_counts.get('L', 0) / total_matches * 100, 1)}
    ]
    
    # Generate venue analysis for the filtered data
    venue_analysis = {
        "Home": {"Win": 35, "Draw": 30, "Loss": 35},
        "Away": {"Win": 30, "Draw": 35, "Loss": 35}
    }
    
    if 'venue' in filtered_data.columns and 'result' in filtered_data.columns:
        for venue in ['Home', 'Away']:
            venue_data = filtered_data[filtered_data['venue'] == venue]
            if len(venue_data) > 0:
                venue_wins = sum(venue_data['result'] == 'W')
                venue_draws = sum(venue_data['result'] == 'D')
                venue_losses = sum(venue_data['result'] == 'L')
                total = len(venue_data)
                
                venue_analysis[venue] = {
                    "Win": round(venue_wins / total * 100, 1),
                    "Draw": round(venue_draws / total * 100, 1),
                    "Loss": round(venue_losses / total * 100, 1)
                }
    
    # Team performance - unchanged, this should work for all teams already
    team_performance = {}
    
    if 'team' in data.columns:
        for team in data['team'].unique():
            team_data = data[data['team'] == team]
            
            team_wins = sum(team_data['result'] == 'W') if 'result' in team_data.columns else 0
            team_draws = sum(team_data['result'] == 'D') if 'result' in team_data.columns else 0
            team_losses = sum(team_data['result'] == 'L') if 'result' in team_data.columns else 0
            total = len(team_data) or 1
            
            team_performance[team] = {
                "Win": round(team_wins / total * 100, 1), 
                "Draw": round(team_draws / total * 100, 1), 
                "Loss": round(team_losses / total * 100, 1),
                "WinPercent": round(team_wins / total * 100, 1)
            }
    
    # Generate stats correlation for filtered data
    stats_correlation = [
        {"stat": "Shots on Target", "correlation": 0.75},
        {"stat": "Goals For", "correlation": 0.72},
        {"stat": "Possession", "correlation": 0.58},
        {"stat": "Distance", "correlation": -0.32},
        {"stat": "Goals Against", "correlation": -0.65}
    ]
    
    try:
        # If we have enough filtered data, calculate real correlations
        if len(filtered_data) > 5 and 'result' in filtered_data.columns:
            filtered_data['win'] = (filtered_data['result'] == 'W').astype(int)
            
            # Get available stat columns
            available_stats = [col for col in ['gf', 'ga', 'sh', 'sot'] if col in filtered_data.columns]
            
            if available_stats:
                correlations = filtered_data[available_stats + ['win']].corr()['win'].drop('win')
                
                stats_correlation = []
                stat_names = {'gf': 'Goals For', 'ga': 'Goals Against', 
                             'sh': 'Shots', 'sot': 'Shots on Target'}
                
                for col, corr in correlations.items():
                    stats_correlation.append({
                        "stat": stat_names.get(col, col),
                        "correlation": round(float(corr), 2)
                    })
    except Exception as e:
        print(f"Error calculating correlations: {e}")
        # Keep using default correlations
    
    return {
        "resultDistribution": result_distribution,
        "venueAnalysis": venue_analysis,
        "teamPerformance": team_performance,
        "statsCorrelation": stats_correlation
    }
# api/main.py - Enhanced predict endpoint

# api/main.py - Complete replacement for the predict endpoint
@app.post("/predict-ensemble/")
async def predict_match_ensemble(prediction_request: dict):
    """Make predictions using the ensemble model"""
    if not hasattr(app.state, 'ensemble_model') or app.state.ensemble_model is None:
        # Fallback to simple prediction if ensemble model not available
        return await predict_match_simple(prediction_request)
    
    try:
        # Extract basic info
        home_team = prediction_request.get('home_team', '')
        away_team = prediction_request.get('away_team', '')
        team_to_predict = prediction_request.get('team_to_predict', 'home').lower()
        
        # Determine team and venue
        if team_to_predict == 'home':
            team = home_team
            opponent = away_team
            venue = 'Home'
        else:
            team = away_team
            opponent = home_team
            venue = 'Away'
            
        # Create match details dictionary
        match_details = {
            "date": prediction_request.get('match_date', pd.Timestamp.now().strftime('%Y-%m-%d')),
            "time": prediction_request.get('match_time', '15:00'),
            "team": team,
            "opponent": opponent,
            "venue": venue,
            "gf_rolling": float(prediction_request.get('goals_for', 1.5)),
            "ga_rolling": float(prediction_request.get('goals_against', 1.0)),
            "sh_rolling": float(prediction_request.get('shots', 12.0)),
            "sot_rolling": float(prediction_request.get('shots_on_target', 5.0)),
        }
        
        # Add optional stats if provided
        optional_fields = {
            "dist_rolling": "distance", 
            "fk_rolling": "free_kicks", 
            "pk_rolling": "penalties", 
            "pkatt_rolling": "penalty_attempts"
        }
        
        for model_field, request_field in optional_fields.items():
            if request_field in prediction_request and prediction_request[request_field] is not None:
                match_details[model_field] = float(prediction_request[request_field])
        
        # Prepare data for prediction
        match_df = prepare_match_prediction_data(match_details, app.state.processed_data)
        
        # Extract features used in training
        predictors = app.state.ensemble_model.predictors
        available_predictors = [p for p in predictors if p in match_df.columns]
        
        # Make sure all predictors exist
        for p in predictors:
            if p not in match_df.columns:
                match_df[p] = 0  # Default value
        
        # Make prediction with ensemble model
        win_probability = float(app.state.ensemble_model.predict_proba(match_df[predictors])[0][1])
        prediction = "WIN" if win_probability > 0.5 else "NOT WIN"
        
        # Get feature importance from ensemble model
        feature_importance = app.state.ensemble_model.get_feature_importance()
        key_factors = feature_importance.head(5).to_dict('records')
        
        # Compare with original model if available
        model_comparison = {}
        if hasattr(app.state, 'model') and app.state.model is not None:
            try:
                original_prob = float(app.state.model.predict_proba(match_df[predictors])[0][1])
                model_comparison = {
                    "rf_only_probability": original_prob,
                    "ensemble_probability": win_probability,
                    "probability_difference": win_probability - original_prob
                }
            except:
                pass
        
        return {
            "team": team,
            "opponent": opponent,
            "win_probability": win_probability,
            "prediction": prediction,
            "key_factors": key_factors,
            "model_version": app.state.ensemble_model.model_version,
            "model_comparison": model_comparison
        }
        
    except Exception as e:
        print(f"Error in ensemble prediction: {e}")
        import traceback
        traceback.print_exc()
        # Fall back to simple prediction
        return await predict_match_simple(prediction_request)

@app.post("/predict/")
async def predict_match(prediction_request: dict):  # Change to accept a dictionary instead of a model
    print(f"Raw prediction request: {prediction_request}")
    
    # Force basic validation manually
    required_fields = ['home_team', 'away_team', 'match_date', 'match_time', 'team_to_predict',
                      'goals_for', 'goals_against', 'shots', 'shots_on_target']
    
    for field in required_fields:
        if field not in prediction_request:
            return {"error": f"Missing required field: {field}"}
    
    try:
        # Manual parsing without validation model
        home_team = prediction_request['home_team']
        away_team = prediction_request['away_team']
        team_to_predict = prediction_request['team_to_predict'].lower()
        
        # Determine which team to predict for
        if team_to_predict == "home":
            team = home_team
            opponent = away_team
            venue = "Home"
        else:
            team = away_team
            opponent = home_team
            venue = "Away"
        
        # Use simple fallback logic for prediction
        goals_for = float(prediction_request['goals_for'])
        goals_against = float(prediction_request['goals_against'])
        
        # Simple win probability calculation
        base_probability = 0.5
        if goals_for > goals_against:
            base_probability += 0.2
        else:
            base_probability -= 0.1
            
        # Home advantage
        if venue == "Home":
            base_probability += 0.1
            
        # Keep within bounds
        win_probability = max(0.1, min(0.9, base_probability))
        
        # Determine outcome
        prediction = "WIN" if win_probability > 0.5 else "NOT WIN"
        
        # Create mock key factors
        key_factors = [
            {"Feature": "Goals For", "Importance": 0.35},
            {"Feature": "Goals Against", "Importance": 0.25},
            {"Feature": "Home Advantage", "Importance": 0.20},
            {"Feature": "Shots", "Importance": 0.12},
            {"Feature": "Shots on Target", "Importance": 0.08}
        ]
        
        # Return simplified response
        return {
            "team": team,
            "opponent": opponent,
            "win_probability": float(win_probability),
            "prediction": prediction,
            "key_factors": key_factors
        }
        
    except Exception as e:
        print(f"Error in prediction: {e}")
        import traceback
        traceback.print_exc()
        # Return error in a way frontend can use
        return {"error": str(e)}
    
@app.post("/predict-simple/")
async def predict_match_simple(prediction_request: dict):
    """A simplified prediction endpoint that doesn't rely on complex model logic"""
    try:
        # Extract basic info
        home_team = prediction_request.get('home_team', '')
        away_team = prediction_request.get('away_team', '')
        team_to_predict = prediction_request.get('team_to_predict', 'home').lower()
        
        # Determine team and venue
        if team_to_predict == 'home':
            team = home_team
            opponent = away_team
            venue = 'Home'
        else:
            team = away_team
            opponent = home_team
            venue = 'Away'
            
        # Get form statistics
        goals_for = float(prediction_request.get('goals_for', 1.5))
        goals_against = float(prediction_request.get('goals_against', 1.0))
        shots = float(prediction_request.get('shots', 12.0))
        shots_on_target = float(prediction_request.get('shots_on_target', 5.0))
        
        # Simple prediction logic
        base_probability = 0.5
        
        # Adjust for form
        form_adjustment = (goals_for - goals_against) * 0.1
        base_probability += form_adjustment
        
        # Adjust for shots efficiency
        if shots > 0:
            shooting_efficiency = min(shots_on_target / shots, 1.0) * 0.1
            base_probability += shooting_efficiency
        
        # Home advantage
        if venue == 'Home':
            base_probability += 0.1
            
        # Ensure probability is between 0 and 1
        win_probability = max(0.1, min(0.9, base_probability))
        
        # Determine result
        prediction = "WIN" if win_probability > 0.5 else "NOT WIN"
        
        # Create simple feature importance
        key_factors = [
            {"Feature": "Goals For", "Importance": 0.35},
            {"Feature": "Goals Against", "Importance": 0.25},
            {"Feature": f"{venue} Advantage", "Importance": 0.20},
            {"Feature": "Shots", "Importance": 0.12},
            {"Feature": "Shots on Target", "Importance": 0.08}
        ]
        
        return {
            "team": team,
            "opponent": opponent,
            "win_probability": float(win_probability),
            "prediction": prediction,
            "key_factors": key_factors
        }
        
    except Exception as e:
        print(f"Error in simple prediction: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}
    
@app.post("/upload-data/")
async def upload_data(file: UploadFile = File(...)):
    print(f"File upload received: {file.filename}, content-type: {file.content_type}")
    
    # Check if file is CSV
    if not file.filename.endswith('.csv'):
        print(f"Invalid file type: {file.filename}")
        raise HTTPException(status_code=400, detail="Only CSV files are supported")
    
    # Read file content
    contents = await file.read()
    content_str = contents.decode('utf-8')
    
    # Print the first 200 characters to debug
    print(f"File content (first 200 chars): {content_str[:200]}...")
    
    try:
        # Parse CSV with detailed error handling
        try:
            # Use pandas to read the CSV
            data = pd.read_csv(io.StringIO(content_str), skipinitialspace=True)
            
            # Print data info for debugging
            print(f"CSV columns found: {data.columns.tolist()}")
            print(f"CSV shape: {data.shape}")
            print(f"First row: {data.iloc[0].to_dict() if not data.empty else 'No data'}")
            
            # Clean up column names (remove whitespace, lowercase)
            data.columns = data.columns.str.strip().str.lower()
            print(f"Cleaned columns: {data.columns.tolist()}")
            
        except Exception as parse_error:
            print(f"CSV parsing error: {parse_error}")
            traceback.print_exc()
            raise HTTPException(status_code=400, detail=f"CSV parsing error: {str(parse_error)}")
        
        # Validate required columns
        required_columns = ['date', 'team', 'opponent', 'venue', 'result']
        missing_columns = [col for col in required_columns if col not in data.columns]
        
        if missing_columns:
            error_msg = f"Missing required columns: {', '.join(missing_columns)}"
            print(error_msg)
            raise HTTPException(status_code=400, detail=error_msg)
        
        # Add default values for missing optional columns
        if 'time' not in data.columns:
            data['time'] = '15:00'  # Default match time
            
        # Convert stats columns to float if they exist
        stat_columns = ['gf', 'ga', 'sh', 'sot']
        for col in stat_columns:
            if col in data.columns:
                try:
                    data[col] = pd.to_numeric(data[col], errors='coerce').fillna(0)
                except Exception as e:
                    print(f"Error converting {col} to numeric: {e}")
                    # Use default instead of failing
                    if col in ['gf', 'ga']:
                        data[col] = data['result'].map({'W': 2.0, 'D': 1.0, 'L': 0.0})
                    elif col == 'sh':
                        data[col] = 10.0
                    elif col == 'sot':
                        data[col] = 4.0
        
        # Add missing stat columns with default values
        for col in stat_columns:
            if col not in data.columns:
                if col in ['gf', 'ga']:
                    # Default based on result
                    data[col] = data['result'].map({'W': 2.0, 'D': 1.0, 'L': 0.0})
                elif col == 'sh':
                    data[col] = 10.0  # Default shots
                elif col == 'sot':
                    data[col] = 4.0   # Default shots on target
        
        # Process data
        try:
            # Convert date to datetime explicitly
            data['date'] = pd.to_datetime(data['date'], errors='coerce')
            
            # Handle any missing or invalid dates
            if data['date'].isna().any():
                print("Warning: Invalid dates detected, filling with today's date")
                data['date'] = data['date'].fillna(pd.Timestamp.now())
            
            # Make sure venue is properly capitalized
            if 'venue' in data.columns:
                data['venue'] = data['venue'].str.capitalize()
                # Make sure it's either 'Home' or 'Away'
                valid_venues = ['Home', 'Away']
                if not data['venue'].isin(valid_venues).all():
                    print("Warning: Invalid venue values detected, correcting to 'Home'")
                    data.loc[~data['venue'].isin(valid_venues), 'venue'] = 'Home'
            
            processed_data = prepare_model_data(data)
            print("Data preprocessing successful")
            
        except Exception as process_error:
            print(f"Error processing data: {process_error}")
            import traceback
            traceback.print_exc()
            # Use a simpler processing approach
            data['date'] = pd.to_datetime(data['date'], errors='coerce')
            data['venue_code'] = data['venue'].map({'Home': 1, 'Away': 0}).fillna(1)
            data['target'] = data['result'].map({'W': 1, 'D': 0, 'L': 0}).fillna(0)
            processed_data = data
            print("Used fallback data processing")
        
        # Train models - both regular and ensemble
        try:
            # Train regular model
            model = train_prediction_model(processed_data)
            print("Regular model training successful")
            
            # Train ensemble model
            ensemble_model = train_ensemble_model(processed_data)
            print("Ensemble model training successful")
        except Exception as model_error:
            print(f"Error training models: {model_error}")
            import traceback
            traceback.print_exc()
            # Create default models
            model = train_prediction_model(None)
            ensemble_model = train_ensemble_model(None)
            print("Used fallback model creation")
        
        # Update application state
        app.state.data = data
        app.state.processed_data = processed_data
        app.state.model = model
        app.state.ensemble_model = ensemble_model
        
        # Ensure data directory exists
        os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
        
        # Save data to file
        try:
            data.to_csv(DATA_PATH, index=False)
            print(f"Data saved to {DATA_PATH}")
        except Exception as save_error:
            print(f"Warning: Could not save data to file: {save_error}")
        
        return {"filename": file.filename, "rows": len(data), "columns": len(data.columns)}
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        print(f"Unexpected error processing file: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")