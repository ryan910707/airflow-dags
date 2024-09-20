import os
import numpy as np
import pandas as pd
from datetime import datetime
from sklearn.model_selection import train_test_split
from sklearn.metrics import r2_score, mean_squared_error

from airflow.decorators import dag, task
from airflow.operators.python import get_current_context
from sklearn.multioutput import MultiOutputClassifier, MultiOutputRegressor

from util import (
    _DC, _EXTRACT_DATETIME, _FE, _GET_MODEL, _GET_MOTION_AND_QA,
    _LOG_MODEL, _LOG_METRIC, _LOG_PARAMETER, _ONEHOT_ENCODING, _SEND_RESULT,
)


@dag(
    schedule=None,
    start_date=datetime(2024, 1, 1),
    tags=[],
    params={
        'model_id': 'multi_y_regressor',
        'date': "2024-01-01",
        'lot_id': "ATWLOT-010124-0852-553-001",
        'features_name': ['equipment_id', 'lf_id', 'proc_datetime', 'heat_pre'],
        'targets_name': [
            "al_squeeze_out_x",
            "al_squeeze_out_y",
            "outer_ball_size_x",
            "outer_ball_size_y",
            "ball_thickness",
            "loop_height",
            "outer_ball_shape",
            "inner_ball_shape",
        ]
    },
)
def model_training():
    """DAG for model training, evaluation, and logging metrics."""

    @task
    def data_collect():
        """Collect data for model training.

        Returns:
            pd.DataFrame: Raw data for training.
        """
        try:
            context = get_current_context()
            params = context['params']
            date = params['date']
            lot_id = params['lot_id']

            print(f"Collecting motion and qa from date: {date}, lot_id: {lot_id}")
            raw_data = _GET_MOTION_AND_QA(date, lot_id)

            return raw_data

        except Exception as e:
            print(f"Error in data_collect: {str(e)}")
            raise e

    @task(multiple_outputs=True)
    def data_preprocess(raw_data):
        """Preprocess the collected data.

        Args:
            raw_data (pd.DataFrame): The raw data.

        Returns:
            dict: A dictionary containing train/test features and targets.
        """
        try:
            context = get_current_context()
            params = context['params']
            features_name = params['features_name']
            targets_name = params['targets_name']
            data = raw_data[features_name + targets_name]

            print("Preprocessing data")
            data = _DC(data)
            feature, target = _FE(data, features_name, targets_name)

            print("Extracting datetime and one-hot encoding")
            feature = _EXTRACT_DATETIME(feature)
            feature = _ONEHOT_ENCODING(feature)

            print("Splitting data into train and test datasets")
            train_feature, test_feature, train_target, test_target = train_test_split(
                feature, target, test_size=0.2, random_state=42)

            return {
                'train_feature': train_feature,
                'test_feature': test_feature,
                'train_target': train_target,
                'test_target': test_target,
            }

        except Exception as e:
            print(f"Error in data_preprocess: {str(e)}")
            raise e

    @task(multiple_outputs=True)
    def train(train_feature, train_target):
        """Train the model using the training data.

        Args:
            train_feature (pd.DataFrame): The training features.
            train_target (pd.DataFrame): The training targets.

        Returns:
            dict: A dictionary containing the trained model and its parameters.
        """
        try:
            feature_tensor = train_feature.values
            target_tensor = train_target.values

            print("Getting and training the model")
            model = _GET_MODEL(target_tensor)
            model.fit(feature_tensor, target_tensor)

            print("Extracting model parameters")
            if isinstance(model, (MultiOutputClassifier, MultiOutputRegressor)):
                base_model = model.estimator
            else:
                base_model = model

            model_parameter = {
                'iterations': base_model.get_param('iterations'),
                'learning_rate': base_model.get_param('learning_rate'),
            }

            return {
                'model': model,
                'model_parameter': model_parameter,
            }

        except Exception as e:
            print(f"Error in train: {str(e)}")
            raise e

    @task
    def save(model):
        """Save the trained model to the server.

        Args:
            model (Any): The trained model.

        Returns:
            dict: The response from the server.
        """
        try:
            context = get_current_context()
            params = context['params']
            model_id = params['model_id']

            print(f"Saving model: {model_id}")
            response = _LOG_MODEL(model_id, model)

            return response

        except Exception as e:
            print(f"Error in save: {str(e)}")
            raise e

    @task
    def predict(model, test_feature):
        """Make predictions using the trained model.

        Args:
            model (Any): The trained model.
            test_feature (pd.DataFrame): The test features.

        Returns:
            pd.DataFrame: The predictions.
        """
        try:
            ctx = get_current_context()
            params = ctx['params']
            targets_name = params['targets_name']
            feature_tensor = test_feature.values

            print("Making predictions")
            prediction_tensor = model.predict(feature_tensor)
            prediction = pd.DataFrame(prediction_tensor, columns=targets_name)

            return prediction

        except Exception as e:
            print(f"Error in predict: {str(e)}")
            raise e

    @task
    def evaluate(target, prediction):
        """Evaluate the model predictions.

        Args:
            target (pd.DataFrame): The true target values.
            prediction (pd.DataFrame): The predicted values.

        Returns:
            dict: A dictionary containing evaluation metrics.
        """
        try:
            print("Evaluating metrics: r2_score, mse_score, pos_max_err, neg_max_err")
            _r2_score = r2_score(target, prediction)
            _mse_score = mean_squared_error(target, prediction)
            errors = prediction.values - target.values
            _pos_max_err = errors.max()
            _neg_max_err = errors.min()

            return {
                'r2_score': _r2_score,
                'mse_score': _mse_score,
                'pos_max_err': _pos_max_err,
                'neg_max_err': _neg_max_err,
            }

        except Exception as e:
            print(f"Error in evaluate: {str(e)}")
            raise e

    @task
    def collect_metric(metrics, parameters):
        """Log evaluation metrics and model parameters to the server.

        Args:
            metrics (dict): The evaluation metrics.
            parameters (dict): The model parameters.

        Returns:
            dict: The responses from the server.
        """
        try:
            context = get_current_context()
            params = context['params']
            model_id = params['model_id']

            print("Saving metrics and parameters")
            responses = {
                'metric': _LOG_METRIC(model_id, metrics),
                'parameter': _LOG_PARAMETER(model_id, parameters)
            }

            return responses

        except Exception as e:
            print(f"Error in collect_metric: {str(e)}")
            raise e

    @task
    def send_result(metrics):
        """Send the evaluation metrics to the result server.

        Args:
            metrics (dict): The evaluation metrics.

        Returns:
            dict: The response from the server.
        """
        try:
            context = get_current_context()
            params = context['params']
            model_id = params['model_id']
            dag_params = context['dag_run']

            print("Sending result to result server")
            response = _SEND_RESULT(model_id, dag_params, metrics)

            return response

        except Exception as e:
            print(f"Error in send_result: {str(e)}")
            raise e
    
    @task.branch(task_id="branching")
    def check_metric(metrics):
        """Check if the evaluation metrics are acceptable.
        Args:
            metrics (dict): The evaluation metrics.
        """
        try:
            context = get_current_context()
            params = context['params']
            model_id = params['model_id']

            print("Checking evaluation metrics")
            r2_score = metrics['r2_score']
            mse_score = metrics['mse_score']
            pos_max_err = metrics['pos_max_err']
            neg_max_err = metrics['neg_max_err']

            if mse_score > 50:
                return ["save", "send_result", "collect_metric"]
            else:
                return "failure"
  
        except Exception as e:
            print(f"Error in check_metric: {str(e)}")
            raise e
    
    @task
    def failure():
        """Handle the failure case when metrics are not acceptable."""
        print("Model did not meet the performance criteria.")
        return

    # Task: data collect
    raw_data = data_collect()
    # Task: data preprocess
    data_preprocess_result = data_preprocess(raw_data)
    train_feature = data_preprocess_result['train_feature']
    test_feature = data_preprocess_result['test_feature']
    train_target = data_preprocess_result['train_target']
    test_target = data_preprocess_result['test_target']
    # Task: train
    train_result = train(train_feature, train_target)
    model = train_result['model']
    model_parameter = train_result['model_parameter']

    # Task: predict
    prediction = predict(model, test_feature)
    # Task: evaluate
    metrics = evaluate(test_target, prediction)
    branch_decision = check_metric(metrics)

    # Define possible branches
    save_response = save(model)
    collect_metric_response = collect_metric(metrics, model_parameter)
    send_result_response = send_result(metrics)
    failure_task = failure()

    branch_decision >> [save_response, collect_metric_response, send_result_response]
    branch_decision >> failure_task


# Define the DAG
training_dag = model_training()