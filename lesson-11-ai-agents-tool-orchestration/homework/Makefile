install:
	python -m pip install -r requirements.txt

run:
	python -m streamlit run app.py

eval:
	python -m eval.evaluators

smoke:
	python -c "from src.graph import run_baseline, run_crew; print(run_baseline('Скільки я витратив на каву минулого тижня?')['answer']); print(run_crew('Скільки я витратив на каву минулого тижня?', thread_id='smoke-test')['answer'])"
