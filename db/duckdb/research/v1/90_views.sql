CREATE OR REPLACE VIEW research_inventory AS
SELECT 'dataset' AS kind, dataset_id AS item_id, stage, status, created_at
FROM datasets
UNION ALL
SELECT 'experiment', experiment_id, stage, status, created_at
FROM experiments
UNION ALL
SELECT 'model', model_id, stage, status, created_at
FROM models
UNION ALL
SELECT 'backtest', backtest_id, stage, status, created_at
FROM backtests;
