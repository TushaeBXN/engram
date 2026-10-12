"""Build the tiny stand-in reranker used by tests/test_reranker.py.

It has the same inputs and output as a real ms-marco cross-encoder
(input_ids, attention_mask, token_type_ids -> logits [batch, 1]) but scores a
(query, passage) pair as the number of passage tokens that also occur in the
query, so tests can check the ONNX plumbing without a 90 MB download.

Regenerate with:  pip install onnx && python tests/fixtures/tiny_reranker/make_tiny_reranker.py
"""

from pathlib import Path

import onnx
from onnx import TensorProto, helper
from tokenizers import Tokenizer, models, normalizers, pre_tokenizers, processors

HERE = Path(__file__).resolve().parent
WORDS = ["jazz", "music", "evening", "brian", "likes", "tea", "garden", "car", "blue", "what", "does"]


def build_tokenizer() -> None:
    vocab = {"[PAD]": 0, "[UNK]": 1, "[CLS]": 2, "[SEP]": 3}
    vocab.update({w: i + 4 for i, w in enumerate(WORDS)})
    tok = Tokenizer(models.WordLevel(vocab=vocab, unk_token="[UNK]"))
    tok.normalizer = normalizers.Lowercase()
    tok.pre_tokenizer = pre_tokenizers.Whitespace()
    tok.post_processor = processors.TemplateProcessing(
        single="[CLS] $A [SEP]",
        pair="[CLS] $A [SEP] $B:1 [SEP]:1",
        special_tokens=[("[CLS]", 2), ("[SEP]", 3)],
    )
    tok.save(str(HERE / "tokenizer.json"))


def build_model() -> None:
    # score = sum over passage tokens p (type 1, not padding, not special) of
    #         [p appears among the query tokens (type 0)]
    ids = helper.make_tensor_value_info("input_ids", TensorProto.INT64, ["b", "l"])
    mask = helper.make_tensor_value_info("attention_mask", TensorProto.INT64, ["b", "l"])
    types = helper.make_tensor_value_info("token_type_ids", TensorProto.INT64, ["b", "l"])
    out = helper.make_tensor_value_info("logits", TensorProto.FLOAT, ["b", 1])
    four = helper.make_tensor("four", TensorProto.INT64, [], [4])
    axes_last = helper.make_tensor("axes_last", TensorProto.INT64, [1], [-1])
    axes_2 = helper.make_tensor("axes_2", TensorProto.INT64, [1], [2])
    axes_1 = helper.make_tensor("axes_1", TensorProto.INT64, [1], [1])
    nodes = [
        # word tokens only (ids >= 4), real tokens only
        helper.make_node("GreaterOrEqual", ["input_ids", "four"], ["is_word"]),
        helper.make_node("Cast", ["is_word"], ["word_f"], to=TensorProto.FLOAT),
        helper.make_node("Cast", ["attention_mask"], ["mask_f"], to=TensorProto.FLOAT),
        helper.make_node("Cast", ["token_type_ids"], ["type_f"], to=TensorProto.FLOAT),
        helper.make_node("Mul", ["word_f", "mask_f"], ["real_word"]),
        helper.make_node("Mul", ["real_word", "type_f"], ["passage"]),          # [b, l]
        helper.make_node("Sub", ["real_word", "passage"], ["query"]),           # [b, l]
        # same[b, i, j] = ids[b, i] == ids[b, j]
        helper.make_node("Unsqueeze", ["input_ids", "axes_last"], ["ids_i"]),   # [b, l, 1]
        helper.make_node("Unsqueeze", ["input_ids", "axes_1"], ["ids_j"]),      # [b, 1, l]
        helper.make_node("Equal", ["ids_i", "ids_j"], ["same"]),
        helper.make_node("Cast", ["same"], ["same_f"], to=TensorProto.FLOAT),
        helper.make_node("Unsqueeze", ["query", "axes_1"], ["query_j"]),        # [b, 1, l]
        helper.make_node("Mul", ["same_f", "query_j"], ["hits"]),
        helper.make_node("ReduceMax", ["hits", "axes_2"], ["in_query"], keepdims=0),  # [b, l]
        helper.make_node("Mul", ["in_query", "passage"], ["matched"]),
        helper.make_node("ReduceSum", ["matched", "axes_last"], ["logits"], keepdims=1),
    ]
    graph = helper.make_graph(nodes, "tiny_reranker", [ids, mask, types], [out],
                              initializer=[four, axes_last, axes_2, axes_1])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 18)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    onnx.save(model, str(HERE / "model.onnx"))


if __name__ == "__main__":
    build_tokenizer()
    build_model()
    print("wrote", HERE / "tokenizer.json", HERE / "model.onnx")
